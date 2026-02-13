import io
import logging
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, List

import websockets

logger = logging.getLogger(__name__)


class MsgType(IntEnum):
    Invalid = 0
    FullClientRequest = 0b1
    AudioOnlyClient = 0b10
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    FrontEndResultServer = 0b1100
    Error = 0b1111

    ServerACK = AudioOnlyServer

    def __str__(self) -> str:
        return self.name if self.name else f"MsgType({self.value})"


class MsgTypeFlagBits(IntEnum):
    NoSeq = 0
    PositiveSeq = 0b1
    LastNoSeq = 0b10
    NegativeSeq = 0b11
    WithEvent = 0b100


class VersionBits(IntEnum):
    Version1 = 1
    Version2 = 2
    Version3 = 3
    Version4 = 4


class HeaderSizeBits(IntEnum):
    HeaderSize4 = 1
    HeaderSize8 = 2
    HeaderSize12 = 3
    HeaderSize16 = 4


class SerializationBits(IntEnum):
    Raw = 0
    JSON = 0b1
    Thrift = 0b11
    Custom = 0b1111


class CompressionBits(IntEnum):
    None_ = 0
    Gzip = 0b1
    Custom = 0b1111


class EventType(IntEnum):
    None_ = 0

    StartConnection = 1
    StartTask = 1
    FinishConnection = 2
    FinishTask = 2

    ConnectionStarted = 50
    TaskStarted = 50
    ConnectionFailed = 51
    TaskFailed = 51
    ConnectionFinished = 52
    TaskFinished = 52

    StartSession = 100
    CancelSession = 101
    FinishSession = 102

    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153
    UsageResponse = 154
    ChargeData = 154

    TaskRequest = 200
    UpdateConfig = 201

    AudioMuted = 250

    SayHello = 300

    TTSSentenceStart = 350
    TTSSentenceEnd = 351
    TTSResponse = 352
    TTSEnded = 359
    PodcastRoundStart = 360
    PodcastRoundResponse = 361
    PodcastRoundEnd = 362
    PodcastEnd = 363

    ASRInfo = 450
    ASRResponse = 451
    ASREnded = 459

    ChatTTSText = 500

    ChatResponse = 550
    ChatEnded = 559

    SourceSubtitleStart = 650
    SourceSubtitleResponse = 651
    SourceSubtitleEnd = 652
    TranslationSubtitleStart = 653
    TranslationSubtitleResponse = 654
    TranslationSubtitleEnd = 655

    def __str__(self) -> str:
        return self.name if self.name else f"EventType({self.value})"


@dataclass
class Message:
    version: VersionBits = VersionBits.Version1
    header_size: HeaderSizeBits = HeaderSizeBits.HeaderSize4
    type: MsgType = MsgType.Invalid
    flag: MsgTypeFlagBits = MsgTypeFlagBits.NoSeq
    serialization: SerializationBits = SerializationBits.JSON
    compression: CompressionBits = CompressionBits.None_

    event: EventType = EventType.None_
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0

    payload: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        if len(data) < 3:
            raise ValueError(
                f"Data too short: expected at least 3 bytes, got {len(data)}"
            )

        type_and_flag = data[1]
        msg_type = MsgType(type_and_flag >> 4)
        flag = MsgTypeFlagBits(type_and_flag & 0b00001111)

        msg = cls(type=msg_type, flag=flag)
        msg.unmarshal(data)
        return msg

    def marshal(self) -> bytes:
        buffer = io.BytesIO()
        header = [
            (self.version << 4) | self.header_size,
            (self.type << 4) | self.flag,
            (self.serialization << 4) | self.compression,
        ]
        header_size = 4 * self.header_size
        if padding := header_size - len(header):
            header.extend([0] * padding)
        buffer.write(bytes(header))
        writers = self._get_writers()
        for writer in writers:
            writer(buffer)
        return buffer.getvalue()

    def unmarshal(self, data: bytes) -> None:
        buffer = io.BytesIO(data)
        version_and_header_size = buffer.read(1)[0]
        self.version = VersionBits(version_and_header_size >> 4)
        self.header_size = HeaderSizeBits(version_and_header_size & 0b00001111)
        buffer.read(1)
        serialization_compression = buffer.read(1)[0]
        self.serialization = SerializationBits(serialization_compression >> 4)
        self.compression = CompressionBits(serialization_compression & 0b00001111)
        header_size = 4 * self.header_size
        read_size = 3
        if padding_size := header_size - read_size:
            buffer.read(padding_size)
        readers = self._get_readers()
        for reader in readers:
            reader(buffer)
        remaining = buffer.read()
        if remaining:
            raise ValueError(f"Unexpected data after message: {remaining}")

    def _get_writers(self) -> List[Callable[[io.BytesIO], None]]:
        writers = []
        if self.flag == MsgTypeFlagBits.WithEvent:
            writers.extend([self._write_event, self._write_session_id])
        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                writers.append(self._write_sequence)
        elif self.type == MsgType.Error:
            writers.append(self._write_error_code)
        else:
            raise ValueError(f"Unsupported message type: {self.type}")
        writers.append(self._write_payload)
        return writers

    def _get_readers(self) -> List[Callable[[io.BytesIO], None]]:
        readers = []
        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                readers.append(self._read_sequence)
        elif self.type == MsgType.Error:
            readers.append(self._read_error_code)
        else:
            raise ValueError(f"Unsupported message type: {self.type}")
        if self.flag == MsgTypeFlagBits.WithEvent:
            readers.extend(
                [self._read_event, self._read_session_id, self._read_connect_id]
            )
        readers.append(self._read_payload)
        return readers

    def _write_event(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.event))

    def _write_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
        ]:
            return
        session_id_bytes = self.session_id.encode("utf-8")
        size = len(session_id_bytes)
        if size > 0xFFFFFFFF:
            raise ValueError(f"Session ID size ({size}) exceeds max(uint32)")
        buffer.write(struct.pack(">I", size))
        if size > 0:
            buffer.write(session_id_bytes)

    def _write_sequence(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.sequence))

    def _write_error_code(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">I", self.error_code))

    def _write_payload(self, buffer: io.BytesIO) -> None:
        size = len(self.payload)
        if size > 0xFFFFFFFF:
            raise ValueError(f"Payload size ({size}) exceeds max(uint32)")
        buffer.write(struct.pack(">I", size))
        buffer.write(self.payload)

    def _read_event(self, buffer: io.BytesIO) -> None:
        event_bytes = buffer.read(4)
        if event_bytes:
            self.event = EventType(struct.unpack(">i", event_bytes)[0])

    def _read_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ]:
            return
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                session_id_bytes = buffer.read(size)
                if len(session_id_bytes) == size:
                    self.session_id = session_id_bytes.decode("utf-8")

    def _read_connect_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ]:
            size_bytes = buffer.read(4)
            if size_bytes:
                size = struct.unpack(">I", size_bytes)[0]
                if size > 0:
                    self.connect_id = buffer.read(size).decode("utf-8")

    def _read_sequence(self, buffer: io.BytesIO) -> None:
        sequence_bytes = buffer.read(4)
        if sequence_bytes:
            self.sequence = struct.unpack(">i", sequence_bytes)[0]

    def _read_error_code(self, buffer: io.BytesIO) -> None:
        error_code_bytes = buffer.read(4)
        if error_code_bytes:
            self.error_code = struct.unpack(">I", error_code_bytes)[0]

    def _read_payload(self, buffer: io.BytesIO) -> None:
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                self.payload = buffer.read(size)

    def __str__(self) -> str:
        if self.type in [MsgType.AudioOnlyServer, MsgType.AudioOnlyClient]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                return f"MsgType: {self.type}, EventType:{self.event}, Sequence: {self.sequence}, PayloadSize: {len(self.payload)}"
            return f"MsgType: {self.type}, EventType:{self.event}, PayloadSize: {len(self.payload)}"
        elif self.type == MsgType.Error:
            return f"MsgType: {self.type}, EventType:{self.event}, ErrorCode: {self.error_code}, Payload: {self.payload.decode('utf-8', 'ignore')}"
        else:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                return f"MsgType: {self.type}, EventType:{self.event}, Sequence: {self.sequence}, Payload: {self.payload.decode('utf-8', 'ignore')}"
            return f"MsgType: {self.type}, EventType:{self.event}, Payload: {self.payload.decode('utf-8', 'ignore')}"


async def receive_message(websocket: websockets.WebSocketClientProtocol) -> Message:
    try:
        data = await websocket.recv()
        if isinstance(data, str):
            raise ValueError(f"Unexpected text message: {data}")
        elif isinstance(data, bytes):
            msg = Message.from_bytes(data)
            logger.debug(f"Received: {msg}")
            return msg
        else:
            raise ValueError(f"Unexpected message type: {type(data)}")
    except Exception as e:
        logger.error(f"Failed to receive message: {e}")
        raise


async def wait_for_event(
    websocket: websockets.WebSocketClientProtocol,
    msg_type: MsgType,
    event_type: EventType,
) -> Message:
    while True:
        msg = await receive_message(websocket)
        if msg.type != msg_type or msg.event != event_type:
            logger.debug(f"Skipping unexpected message: {msg}")
            continue
        if msg.type == msg_type and msg.event == event_type:
            return msg


async def full_client_request(
    websocket: websockets.WebSocketClientProtocol, payload: bytes
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.NoSeq)
    msg.payload = payload
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def audio_only_client(
    websocket: websockets.WebSocketClientProtocol, payload: bytes, flag: MsgTypeFlagBits
) -> None:
    msg = Message(type=MsgType.AudioOnlyClient, flag=flag)
    msg.payload = payload
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def start_connection(websocket: websockets.WebSocketClientProtocol) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.StartConnection
    msg.payload = b"{}"
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def finish_connection(websocket: websockets.WebSocketClientProtocol) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.FinishConnection
    msg.payload = b"{}"
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def start_session(
    websocket: websockets.WebSocketClientProtocol, payload: bytes, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.StartSession
    msg.session_id = session_id
    msg.payload = payload
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def finish_session(
    websocket: websockets.WebSocketClientProtocol, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.FinishSession
    msg.session_id = session_id
    msg.payload = b"{}"
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def cancel_session(
    websocket: websockets.WebSocketClientProtocol, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.CancelSession
    msg.session_id = session_id
    msg.payload = b"{}"
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())


async def task_request(
    websocket: websockets.WebSocketClientProtocol, payload: bytes, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.TaskRequest
    msg.session_id = session_id
    msg.payload = payload
    logger.debug(f"Sending: {msg}")
    await websocket.send(msg.marshal())
