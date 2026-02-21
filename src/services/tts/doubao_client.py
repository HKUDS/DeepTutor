import asyncio
import base64
import gzip
import json
import logging
import uuid
from typing import Optional

import websockets

from .doubao_protocol import (
    CompressionBits,
    EventType,
    Message,
    MsgType,
    MsgTypeFlagBits,
    SerializationBits,
    VersionBits,
    receive_message,
    start_connection,
    finish_connection,
    start_session,
    finish_session,
    task_request,
    wait_for_event,
)

logger = logging.getLogger(__name__)


class DoubaoTTSClient:
    def __init__(
        self,
        app_id: str,
        access_token: str,
        cluster: str = "volc_ttos_samantha",
        base_url: str = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary",
    ):
        self.app_id = app_id
        self.access_token = access_token
        self.cluster = cluster
        self.base_url = base_url

    async def generate_audio(self, text: str, voice: str) -> bytes:
        """
        Generate audio from text using Doubao TTS via WebSocket.
        """
        session_id = str(uuid.uuid4())
        audio_data = bytearray()

        headers = {"Authorization": f"Bearer; {self.access_token}"}

        try:
            async with websockets.connect(
                self.base_url, additional_headers=headers
            ) as websocket:
                # 1. Full Client Request (Submit Task)
                request_payload = {
                    "app": {
                        "appid": self.app_id,
                        "token": self.access_token,
                        "cluster": self.cluster,
                    },
                    "user": {"uid": "deeptutor_user"},
                    "audio": {
                        "voice_type": voice,
                        "encoding": "mp3",
                        "compression_rate": 1,
                        "rate": 24000,
                        "speed_ratio": 1.0,
                        "volume_ratio": 1.0,
                        "pitch_ratio": 1.0,
                    },
                    "request": {
                        "reqid": session_id,
                        "text": text,
                        "text_type": "plain",
                        "operation": "submit",
                    },
                }

                payload_bytes = json.dumps(request_payload).encode("utf-8")
                compressed_payload = gzip.compress(payload_bytes)

                msg = Message(
                    type=MsgType.FullClientRequest,
                    flag=MsgTypeFlagBits.NoSeq,
                    serialization=SerializationBits.JSON,
                    compression=CompressionBits.Gzip,
                    payload=compressed_payload,
                )
                
                logger.info(f"Sending submit request for session {session_id}")
                await websocket.send(msg.marshal())

                # 2. Receive Loop
                while True:
                    raw_data = await websocket.recv()
                    if isinstance(raw_data, str):
                        logger.warning(f"Unexpected text message: {raw_data}")
                        continue
                        
                    response_msg = Message.from_bytes(raw_data)

                    # Handle Payload Compression
                    payload = response_msg.payload
                    if response_msg.compression == CompressionBits.Gzip:
                        payload = gzip.decompress(payload)

                    if response_msg.type == MsgType.AudioOnlyServer:
                         # Append audio data
                        audio_data.extend(payload)
                        # Identify if this is the last chunk
                        if response_msg.sequence < 0:
                            logger.info(f"Received last audio chunk for session {session_id}")
                            break
                    
                    elif response_msg.type == MsgType.FullServerResponse:
                        if response_msg.sequence < 0: 
                             break

                    elif response_msg.type == MsgType.Error:
                        logger.error(f"TTS Error {response_msg.error_code}: {payload}")
                        raise ValueError(f"TTS Error {response_msg.error_code}")

        except Exception as e:
            logger.error(f"Doubao TTS generation failed: {e}")
            raise

        return bytes(audio_data)


class DoubaoPodcastClient:
    """
    Client for Doubao Podcast TTS (播客语音合成)
    Documentation: https://www.volcengine.com/docs/6561/1668014?lang=zh
    """
    def __init__(
        self,
        app_id: str,
        access_token: str,
        base_url: str = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts",
    ):
        self.app_id = app_id
        self.access_token = access_token
        self.base_url = base_url

    async def generate_audio_stream(self, text: str, speakers: list[str] = None, speech_rate: float = 1.0):
        """
        Generate podcast audio stream from raw text/markdown.
        Yields audio chunks (bytes).

        Args:
            text: Input text/markdown content
            speakers: List of speaker voice IDs (default: one female + one male)
            speech_rate: Speech speed multiplier 0.5~2.0 (1.0 = normal).
                         Mapped to API's -500~500 scale linearly.
        """
        if not speakers:
             speakers = [
                "zh_female_mizaitongxue_v2_saturn_bigtts",
                "zh_male_dayixiansheng_v2_saturn_bigtts"
            ]

        # Map UI speech_rate (0.5~2.0) to API speech_rate (-500~500)
        # 0.5 -> -500, 1.0 -> 0, 2.0 -> 500  (linear: (rate - 1.0) * 1000 / 1.0)
        # Clamp to valid range
        clamped_rate = max(0.5, min(2.0, speech_rate))
        api_speech_rate = int((clamped_rate - 1.0) * (500 / 1.0))
        # Ensure it stays within -500..500
        api_speech_rate = max(-500, min(500, api_speech_rate))

        request_id = str(uuid.uuid4())
        
        headers = {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "volc.service_type.10050",
            "X-Api-App-Key": "aGjiRDfUWi",
            "X-Api-Request-Id": request_id, 
        }

        req_params = {
            "input_id": request_id,
            "input_text": text,
            "action": 0,
            "input_info": {
                 "only_nlp_text": False,
                 "return_audio_url": False,
            },
            "speaker_info": {
                "speakers": speakers,
                "random_order": False
            },
            "audio_config": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": api_speech_rate
            }
        }

        try:
            async with websockets.connect(
                self.base_url, additional_headers=headers
            ) as websocket:
                
                await start_connection(websocket)
                await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)
                
                session_id = str(uuid.uuid4())
                await start_session(websocket, json.dumps(req_params).encode("utf-8"), session_id)
                await wait_for_event(websocket, MsgType.FullServerResponse, EventType.SessionStarted)
                
                await finish_session(websocket, session_id)
                
                current_round_audio = bytearray()
                
                while True:
                    msg = await receive_message(websocket)
                    
                    if msg.type == MsgType.AudioOnlyServer and msg.event == EventType.PodcastRoundResponse:
                         chunk = msg.payload
                         if chunk:
                             yield chunk
                             current_round_audio.extend(chunk)
                    
                    elif msg.type == MsgType.Error:
                        error_msg = msg.payload.decode('utf-8', errors='ignore')
                        logger.error(f"Server error: {error_msg}")
                        raise RuntimeError(f"Server error: {error_msg}")
                        
                    elif msg.type == MsgType.FullServerResponse:
                        if msg.event == EventType.PodcastRoundStart:
                            data = json.loads(msg.payload.decode('utf-8'))
                            logger.info(f"Podcast round start: {data.get('round_id')}")
                            current_round_audio = bytearray()
                            
                        elif msg.event == EventType.PodcastRoundEnd:
                            data = json.loads(msg.payload.decode('utf-8'))
                            logger.info(f"Podcast round end: {data.get('round_id')}")
                            if data.get("is_error"):
                                raise RuntimeError(f"Round error: {data}")
                            
                        elif msg.event == EventType.PodcastEnd:
                            logger.info("Podcast generation finished")
                            break
                            
                    elif msg.event == EventType.SessionFinished:
                         break
                         
                await finish_connection(websocket)
                await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionFinished)

        except Exception as e:
            logger.error(f"Doubao Podcast stream failed: {e}")
            raise

    async def generate_audio(self, text: str, speakers: list[str] = None, speech_rate: float = 1.0) -> bytes:
        """
        Generate podcast audio from raw text/markdown (non-streaming wrapper).
        """
        audio_data = bytearray()
        async for chunk in self.generate_audio_stream(text, speakers, speech_rate=speech_rate):
            audio_data.extend(chunk)
        return bytes(audio_data)
