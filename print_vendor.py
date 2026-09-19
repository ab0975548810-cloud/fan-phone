"""Server-only Yunweiyin client.

The client is disabled unless explicitly enabled and never logs credentials or
full request bodies. Tests inject a transport; CI cannot reach the real vendor.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time

import requests


class VendorError(RuntimeError):
    pass


class VendorDisabled(VendorError):
    pass


class VendorAmbiguous(VendorError):
    """The remote side may have accepted the operation."""


def yun_sign(device_id, key, once, timestamp):
    raw = f"device_id={device_id}&key={key}&once={once}&time={timestamp}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class YunPrintClient:
    def __init__(self, *, transport=None, env=None, clock=None, nonce=None):
        cfg = os.environ if env is None else env
        self.device_id = str(cfg.get("YUN_PRINT_DEVICE_ID", "")).strip()
        self._key = str(cfg.get("YUN_PRINT_DEVICE_KEY", "")).strip()
        self.base_url = str(cfg.get("YUN_PRINT_BASE_URL", "https://open.yunweiyin.com")).strip().rstrip("/")
        self.enabled = str(cfg.get("YUN_PRINT_ENABLED", "")).lower() in ("1", "true", "yes")
        self.transport = transport
        self.clock = clock or time.time
        self.nonce = nonce or (lambda: secrets.token_hex(16))
        self._ci = str(cfg.get("CI", "")).lower() in ("1", "true", "yes")

    @property
    def ready(self):
        return bool(self.enabled and self.device_id and self._key and (self.transport or not self._ci))

    def _ensure(self):
        if not self.enabled:
            raise VendorDisabled("雲打印尚未啟用")
        if not self.device_id or not self._key:
            raise VendorDisabled("雲打印設備憑證未設定")
        if self._ci and self.transport is None:
            raise VendorDisabled("CI 禁止連線真實雲打印服務")

    def auth_fields(self):
        self._ensure()
        once = str(self.nonce())
        timestamp = str(int(self.clock()))
        return {
            "device_id": self.device_id,
            "once": once,
            "time": timestamp,
            "sign": yun_sign(self.device_id, self._key, once, timestamp),
        }

    def valid_callback(self, payload):
        if not self.device_id or not self._key:
            return False
        device_id = str(payload.get("device_id", ""))
        once = str(payload.get("once", ""))
        timestamp = str(payload.get("time", ""))
        supplied = str(payload.get("sign", "")).lower()
        if not device_id or device_id != self.device_id or not once or not timestamp or not supplied:
            return False
        try:
            if abs(int(self.clock()) - int(timestamp)) > 600:
                return False
        except (TypeError, ValueError):
            return False
        expected = yun_sign(device_id, self._key, once, timestamp)
        return secrets.compare_digest(supplied, expected)

    @staticmethod
    def _unpack(raw):
        if not isinstance(raw, dict):
            raise VendorAmbiguous("雲打印回應格式無法確認")
        if "code" in raw:
            success = str(raw.get("code")) == "0"
        elif "status_code" in raw:
            success = str(raw.get("status_code")) == "0"
        elif raw.get("success") is True:
            success = True
        else:
            raise VendorAmbiguous("雲打印回應缺少明確成功訊號")
        if not success:
            raise VendorError("雲打印拒絕此操作")
        data = raw.get("data", raw)
        return data if isinstance(data, (dict, list)) else {"value": data}

    def _post(self, path, fields):
        self._ensure()
        payload = {**self.auth_fields(), **fields}
        if self.transport is not None:
            try:
                return self._unpack(self.transport(path, payload))
            except (VendorError, VendorAmbiguous):
                raise
            except TimeoutError as exc:
                raise VendorAmbiguous("雲打印連線逾時，必須先查核任務") from exc
        try:
            response = requests.post(self.base_url + path, data=payload, timeout=(5, 20))
        except requests.Timeout as exc:
            raise VendorAmbiguous("雲打印連線逾時，必須先查核任務") from exc
        except requests.RequestException as exc:
            raise VendorAmbiguous("雲打印連線中斷，必須先查核任務") from exc
        if response.status_code >= 500:
            raise VendorAmbiguous("雲打印服務暫時異常，必須先查核任務")
        if response.status_code < 200 or response.status_code >= 300:
            raise VendorError("雲打印拒絕此操作")
        try:
            return self._unpack(response.json())
        except ValueError as exc:
            raise VendorAmbiguous("雲打印回應無法確認") from exc

    def receive_task(self, job, file_url, callback_url):
        return self._post("/api/Device/receiveTask", {
            "order_id": job["order_id"],
            "name": f"{job['order_id']} #{job['attempt_no']}",
            "file": file_url,
            "copies": job["copies"],
            "width": job["width_mm"],
            "height": job["height_mm"],
            "left": job["left_mm"],
            "top": job["top_mm"],
            "spot_color": job["spot_color"],
            "channel": job["channel"],
            "angle": job["angle"],
            "callback": callback_url,
        })

    def start_print(self, taskid):
        return self._post("/api/Device/startPrint", {"taskid": taskid})

    def cancel_task(self, taskid):
        return self._post("/api/Device/cancelTask", {"taskid": taskid})

    def get_all_tasks(self):
        return self._post("/api/Device/getAllTasks", {})

    def get_stocks(self):
        return self._post("/api/Device/getStocks", {})
