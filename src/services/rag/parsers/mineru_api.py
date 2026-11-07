# -*- coding: utf-8 -*-
"""
MinerU Cloud API Client
========================

Provides document parsing via MinerU's cloud API (https://mineru.net) as an
alternative to running MinerU locally. This is useful when:
- Local GPU resources are unavailable
- Processing needs to be offloaded to the cloud
- Running on machines without MinerU installed

API flow:
1. Request upload URLs via POST /api/v4/file-urls/batch
2. Upload files via PUT to the returned URLs
3. Poll for results via GET /api/v4/extract-results/batch/{batch_id}
4. Download and extract the result ZIP (contains content_list, markdown, images)
"""

import asyncio
import io
import json
import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

logger = logging.getLogger(__name__)

# MinerU API base URL
MINERU_API_BASE = "https://mineru.net/api/v4"

# Default polling settings
DEFAULT_POLL_INTERVAL = 5  # seconds
DEFAULT_POLL_TIMEOUT = 600  # 10 minutes max


class MinerUAPIError(Exception):
    """Exception raised for MinerU API errors."""

    def __init__(self, code: int, message: str, trace_id: str = ""):
        self.code = code
        self.message = message
        self.trace_id = trace_id
        super().__init__(f"MinerU API error [{code}]: {message} (trace_id: {trace_id})")


class MinerUAPIClient:
    """
    Client for MinerU Cloud API (https://mineru.net).

    Handles file upload, task submission, polling for results, and
    downloading/extracting parsed content.

    Usage:
        client = MinerUAPIClient(token="your-api-token")
        content_list, md_content = await client.parse_file(
            file_path="document.pdf",
            output_dir="./output",
        )
    """

    def __init__(
        self,
        token: Optional[str] = None,
        model_version: str = "vlm",
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        poll_timeout: int = DEFAULT_POLL_TIMEOUT,
    ):
        """
        Initialize MinerU API client.

        Args:
            token: MinerU API token (from https://mineru.net).
                   Falls back to MINERU_API_TOKEN env var.
            model_version: Model version to use ("pipeline", "vlm", "MinerU-HTML").
                          Default is "vlm" for best accuracy.
            enable_formula: Whether to enable formula recognition.
            enable_table: Whether to enable table recognition.
            language: Document language (default "ch" for Chinese+English).
            poll_interval: Seconds between polling attempts.
            poll_timeout: Maximum seconds to wait for results.
        """
        self.token = token or os.getenv("MINERU_API_TOKEN", "")
        if not self.token:
            raise ValueError(
                "MinerU API token is required. Set MINERU_API_TOKEN environment variable "
                "or pass token parameter. Get your token from https://mineru.net"
            )

        self.model_version = model_version
        self.enable_formula = enable_formula
        self.enable_table = enable_table
        self.language = language
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _request_upload_urls(
        self,
        file_names: List[str],
        data_ids: Optional[List[str]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Request file upload URLs from MinerU API.

        Args:
            file_names: List of file names to upload.
            data_ids: Optional list of data IDs for tracking.

        Returns:
            Tuple of (batch_id, list of upload URLs)
        """
        files_payload = []
        for i, name in enumerate(file_names):
            entry = {"name": name}
            if data_ids and i < len(data_ids):
                entry["data_id"] = data_ids[i]
            files_payload.append(entry)

        payload = {
            "files": files_payload,
            "model_version": self.model_version,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
        }

        url = f"{MINERU_API_BASE}/file-urls/batch"
        logger.info(f"Requesting upload URLs for {len(file_names)} files...")

        response = requests.post(url, headers=self._headers, json=payload, timeout=30)

        if response.status_code != 200:
            raise MinerUAPIError(
                code=response.status_code,
                message=f"HTTP {response.status_code}: {response.text}",
            )

        result = response.json()
        if result.get("code") != 0:
            raise MinerUAPIError(
                code=result.get("code", -1),
                message=result.get("msg", "Unknown error"),
                trace_id=result.get("trace_id", ""),
            )

        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]

        logger.info(f"Got batch_id: {batch_id}, {len(file_urls)} upload URLs")
        return batch_id, file_urls

    def _upload_file(self, upload_url: str, file_path: Union[str, Path]) -> bool:
        """
        Upload a file to the pre-signed URL.

        Args:
            upload_url: Pre-signed upload URL from MinerU.
            file_path: Local file path.

        Returns:
            True if upload succeeded.
        """
        file_path = Path(file_path)
        logger.info(f"Uploading {file_path.name} ({file_path.stat().st_size / 1024:.1f} KB)...")

        with open(file_path, "rb") as f:
            response = requests.put(upload_url, data=f, timeout=300)

        if response.status_code == 200:
            logger.info(f"  ✓ Upload successful: {file_path.name}")
            return True
        else:
            logger.error(
                f"  ✗ Upload failed: {file_path.name} "
                f"(HTTP {response.status_code}: {response.text})"
            )
            return False

    def _poll_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """
        Poll for batch extraction results until all tasks complete.

        Args:
            batch_id: Batch ID from upload request.

        Returns:
            List of extraction result dicts.

        Raises:
            TimeoutError: If polling exceeds timeout.
            MinerUAPIError: If API returns an error.
        """
        url = f"{MINERU_API_BASE}/extract-results/batch/{batch_id}"
        start_time = time.time()

        logger.info(f"Polling for results (batch_id: {batch_id})...")

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.poll_timeout:
                raise TimeoutError(
                    f"MinerU API polling timed out after {self.poll_timeout}s "
                    f"for batch_id: {batch_id}"
                )

            response = requests.get(url, headers=self._headers, timeout=30)

            if response.status_code != 200:
                raise MinerUAPIError(
                    code=response.status_code,
                    message=f"HTTP {response.status_code}: {response.text}",
                )

            result = response.json()
            if result.get("code") != 0:
                raise MinerUAPIError(
                    code=result.get("code", -1),
                    message=result.get("msg", "Unknown error"),
                    trace_id=result.get("trace_id", ""),
                )

            extract_results = result["data"]["extract_result"]

            # Check overall status
            all_done = True
            has_failed = False
            for item in extract_results:
                state = item.get("state", "")
                if state == "failed":
                    has_failed = True
                    logger.error(
                        f"  ✗ Parsing failed for {item.get('file_name')}: "
                        f"{item.get('err_msg', 'Unknown error')}"
                    )
                elif state not in ("done", "converting"):
                    all_done = False
                    # Log progress info
                    progress = item.get("extract_progress", {})
                    if progress:
                        logger.info(
                            f"  ⏳ {item.get('file_name')}: {state} "
                            f"({progress.get('extracted_pages', '?')}/"
                            f"{progress.get('total_pages', '?')} pages)"
                        )
                    else:
                        logger.info(f"  ⏳ {item.get('file_name')}: {state}")

            if all_done or has_failed:
                completed = [r for r in extract_results if r.get("state") == "done"]
                failed = [r for r in extract_results if r.get("state") == "failed"]

                logger.info(
                    f"Polling complete: {len(completed)} done, {len(failed)} failed "
                    f"(elapsed: {elapsed:.1f}s)"
                )

                if has_failed and not completed:
                    failed_msgs = [
                        f"{r.get('file_name')}: {r.get('err_msg', 'Unknown')}"
                        for r in failed
                    ]
                    raise MinerUAPIError(
                        code=-60010,
                        message=f"All files failed to parse: {'; '.join(failed_msgs)}",
                    )

                return extract_results

            time.sleep(self.poll_interval)

    def _download_and_extract_zip(
        self,
        zip_url: str,
        output_dir: Union[str, Path],
        file_stem: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Download result ZIP and extract content_list and images.

        Args:
            zip_url: URL to the result ZIP file.
            output_dir: Directory to extract results into.
            file_stem: Original file name stem for locating results.

        Returns:
            Tuple of (content_list, markdown_content)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading results ZIP for '{file_stem}'...")

        response = requests.get(zip_url, timeout=300, stream=True)
        if response.status_code != 200:
            raise MinerUAPIError(
                code=response.status_code,
                message=f"Failed to download ZIP: HTTP {response.status_code}",
            )

        # Extract ZIP to a temp dir first, then move to output_dir
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_bytes = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_bytes, "r") as zf:
                zf.extractall(temp_dir)

            temp_path = Path(temp_dir)

            # Find content_list JSON
            content_list = []
            md_content = ""

            # The ZIP structure varies, search recursively for the files
            content_list_files = list(temp_path.rglob("*_content_list.json"))
            md_files = list(temp_path.rglob("*.md"))
            image_dirs = list(temp_path.rglob("images"))

            # Read content_list
            if content_list_files:
                cl_file = content_list_files[0]
                logger.info(f"  Found content_list: {cl_file.name}")
                with open(cl_file, "r", encoding="utf-8") as f:
                    content_list = json.load(f)
            else:
                logger.warning("  ⚠ No content_list JSON found in ZIP")

            # Read markdown
            if md_files:
                md_file = md_files[0]
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()

            # Copy images to output_dir/images/
            images_output = output_dir / "images"
            for img_dir in image_dirs:
                if img_dir.is_dir():
                    images_output.mkdir(parents=True, exist_ok=True)
                    for img_file in img_dir.iterdir():
                        if img_file.is_file():
                            dest = images_output / img_file.name
                            shutil.copy2(img_file, dest)

            # Fix image paths in content_list to point to the output directory
            for item in content_list:
                if isinstance(item, dict):
                    for field_name in ["img_path", "table_img_path", "equation_img_path"]:
                        if field_name in item and item[field_name]:
                            img_path = item[field_name]
                            # Convert relative path to absolute path under output_dir
                            img_filename = Path(img_path).name
                            absolute_path = str((images_output / img_filename).resolve())
                            item[field_name] = absolute_path

            # Save content_list to output_dir
            content_list_output = output_dir / f"{file_stem}_content_list.json"
            with open(content_list_output, "w", encoding="utf-8") as f:
                json.dump(content_list, f, ensure_ascii=False, indent=2)

            # Save markdown to output_dir
            if md_content:
                md_output = output_dir / f"{file_stem}.md"
                with open(md_output, "w", encoding="utf-8") as f:
                    f.write(md_content)

            logger.info(
                f"  ✓ Extracted {len(content_list)} content blocks, "
                f"{len(list(images_output.glob('*'))) if images_output.exists() else 0} images"
            )

        return content_list, md_content

    async def parse_files(
        self,
        file_paths: List[Union[str, Path]],
        output_dir: Union[str, Path],
        data_ids: Optional[List[str]] = None,
    ) -> Dict[str, Tuple[List[Dict[str, Any]], str]]:
        """
        Parse multiple files via MinerU Cloud API.

        Args:
            file_paths: List of local file paths to parse.
            output_dir: Directory to store parsed results.
            data_ids: Optional data IDs for each file.

        Returns:
            Dict mapping file_stem -> (content_list, doc_id_placeholder)
        """
        file_paths = [Path(p) for p in file_paths]
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Validate files exist
        for fp in file_paths:
            if not fp.exists():
                raise FileNotFoundError(f"File not found: {fp}")

        file_names = [fp.name for fp in file_paths]

        # Step 1: Request upload URLs
        batch_id, upload_urls = await asyncio.to_thread(
            self._request_upload_urls, file_names, data_ids
        )

        if len(upload_urls) != len(file_paths):
            raise MinerUAPIError(
                code=-1,
                message=f"Got {len(upload_urls)} upload URLs for {len(file_paths)} files",
            )

        # Step 2: Upload files
        for file_path, upload_url in zip(file_paths, upload_urls):
            success = await asyncio.to_thread(self._upload_file, upload_url, file_path)
            if not success:
                raise MinerUAPIError(
                    code=-1,
                    message=f"Failed to upload file: {file_path.name}",
                )

        # Step 3: Poll for results
        extract_results = await asyncio.to_thread(self._poll_results, batch_id)

        # Step 4: Download and extract results
        results = {}
        for item in extract_results:
            if item.get("state") != "done":
                continue

            file_name = item.get("file_name", "")
            zip_url = item.get("full_zip_url", "")
            if not zip_url:
                logger.warning(f"No ZIP URL for {file_name}, skipping")
                continue

            file_stem = Path(file_name).stem
            file_output_dir = output_dir / file_stem

            content_list, md_content = await asyncio.to_thread(
                self._download_and_extract_zip,
                zip_url,
                file_output_dir,
                file_stem,
            )

            results[file_stem] = (content_list, md_content)

        return results

    async def parse_file(
        self,
        file_path: Union[str, Path],
        output_dir: Union[str, Path],
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Parse a single file via MinerU Cloud API.

        Convenience wrapper around parse_files for single-file use.

        Args:
            file_path: Local file path to parse.
            output_dir: Directory to store parsed results.

        Returns:
            Tuple of (content_list, markdown_content)
        """
        file_path = Path(file_path)
        results = await self.parse_files([file_path], output_dir)

        file_stem = file_path.stem
        if file_stem in results:
            return results[file_stem]

        # If file_stem doesn't match (e.g. due to naming differences), return first result
        if results:
            return next(iter(results.values()))

        raise MinerUAPIError(
            code=-1,
            message=f"No parsing results returned for {file_path.name}",
        )
