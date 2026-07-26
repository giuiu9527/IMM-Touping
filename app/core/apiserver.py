# -*- coding: utf-8 -*-
"""本地控制 API —— 供手机端 autox.js 通过 adb reverse 调用，实现自动录制/停止/改名归档。

设计要点（改动前先看这几条）：
- 连通方式：**adb reverse**。电脑给每台在线设备执行
      adb -s <serial> reverse tcp:<phone_port> tcp:<该设备专属 pc_port>
  手机脚本永远访问 `127.0.0.1:<phone_port>`（所有手机同一份、写死、零配置），
  电脑按“请求到达哪个 pc_port”反查是哪台设备 —— 手机无需上报身份，也无伪造问题。
- 每台设备一个独立的 ThreadingHTTPServer（都绑 127.0.0.1，仅本机+被 reverse 的手机可达）。
- 处理器在各自守护线程里跑，通过回调 `dispatch(serial, action, params) -> dict` 交给 App 执行；
  涉及 UI 的部分由 App 内部用 root.after 调回主线程。

对外接口（GET / POST 均可，参数走 query 或表单/JSON body）：
    /ping                                  -> {ok, serial, app, version}
    /status                                -> {ok, recording, file}
    /record/start?name=                    -> 开始录制，返回 {ok, id, file}（name 可留空=临时名）
    /record/stop?name=                     -> 停止录制并干净收尾，返回 {ok, id, file}
    /record/rename?name=&folder=&id=       -> 改名并归档到子文件夹，返回 {ok, file}
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


class ApiServer:
    def __init__(self, adb, dispatch, phone_port: int = 8300, base_pc_port: int = 8300):
        self.adb = adb
        self.dispatch = dispatch          # callable(serial, action, params) -> dict
        self.phone_port = phone_port
        self.base_pc_port = base_pc_port
        self.enabled = True
        self._servers = {}                # serial -> (pc_port, httpd)
        self._used_ports = set()
        self._lock = threading.Lock()

    # ---------- 生命周期（跟随在线设备增删，幂等） ----------
    def sync(self, online_serials):
        """按当前在线设备增删监听。会调用 adb（可能阻塞），请在后台线程调用。"""
        if not self.enabled:
            self.stop_all()
            return
        online = set(online_serials)
        with self._lock:
            for s in list(self._servers.keys()):
                if s not in online:
                    self._drop_locked(s)
            for s in online:
                if s not in self._servers:
                    self._add_locked(s)

    def _pick_port(self) -> int:
        p = self.base_pc_port
        while p in self._used_ports:
            p += 1
        return p

    def _add_locked(self, serial):
        for _ in range(30):
            port = self._pick_port()
            try:                                  # 先占电脑端口，确保能绑定
                httpd = ThreadingHTTPServer(("127.0.0.1", port), self._make_handler(serial))
            except OSError:
                self._used_ports.add(port)        # 端口被别的程序占了，跳过再试
                continue
            ok, _out = self.adb.reverse(serial, self.phone_port, port)
            if not ok:                            # 设备可能刚掉线
                try:
                    httpd.server_close()
                except Exception:
                    pass
                return
            httpd.daemon_threads = True
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self._servers[serial] = (port, httpd)
            self._used_ports.add(port)
            return

    def _drop_locked(self, serial):
        entry = self._servers.pop(serial, None)
        if not entry:
            return
        port, httpd = entry
        self._used_ports.discard(port)
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        try:
            self.adb.reverse_remove(serial, self.phone_port)
        except Exception:
            pass

    def stop_all(self):
        with self._lock:
            for s in list(self._servers.keys()):
                self._drop_locked(s)

    def ports(self):
        """当前 serial -> pc_port 映射（调试/展示用）。"""
        with self._lock:
            return {s: p for s, (p, _h) in self._servers.items()}

    # ---------- HTTP 处理器 ----------
    def _make_handler(self, serial):
        dispatch = self.dispatch

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):            # 静音，不往控制台打日志
                pass

            def _reply(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

            def _collect(self):
                parsed = urlparse(self.path)
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    raw = self.rfile.read(length).decode("utf-8", "replace")
                    try:
                        params.update(json.loads(raw))
                    except Exception:
                        params.update({k: v[0] for k, v in parse_qs(raw).items()})
                return parsed.path.strip("/").lower(), params

            def _handle(self):
                try:
                    action, params = self._collect()
                    result = dispatch(serial, action, params)
                    if not isinstance(result, dict):
                        result = {"ok": False, "error": "bad result"}
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                self._reply(result, 200 if result.get("ok") else 400)

            do_GET = _handle
            do_POST = _handle

        return Handler
