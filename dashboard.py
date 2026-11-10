"""Painel visual do tcp-udp-example.

Roda o receptor (receiver.py) em laço, captura os pacotes da rede com o
tshark e mostra tudo em tempo real num servidor web local, via
Server-Sent Events (SSE).

    python dashboard.py      ->  abra http://localhost:8000

Requer em receiver.py a variável global `on_message` e a chamada
`on_message(proto, seq, interval)` dentro dos laços de recepção.
"""
import atexit
import json
import queue
import struct
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import receiver

HTTP_PORT = 8000
HTML_FILE = Path(__file__).with_name("dashboard.html")

# Captura de pacotes (camada 2 a 4): tshark vem junto com o Wireshark.
TSHARK = r"C:\Program Files\Wireshark\tshark.exe"
CAPTURE_INTERFACE = "Ethernet"  # nome da placa, como aparece em `tshark -D`
TSHARK_FIELDS = [
    "frame.time_epoch", "ip.src", "ip.dst",
    "tcp.srcport", "tcp.dstport", "udp.srcport", "udp.dstport",
    "tcp.flags.str", "tcp.seq", "tcp.ack", "tcp.len", "udp.length",
    "frame.len", "tcp.payload", "udp.payload", "_ws.expert.message",
]
TCP_FLAGS = {"S": "SYN", "F": "FIN", "R": "RST", "P": "PSH", "A": "ACK", "U": "URG"}
FLAG_ORDER = ["SYN", "FIN", "RST", "PSH", "ACK", "URG"]

_clients = []                 # uma fila por aba do navegador conectada
_clients_lock = threading.Lock()
_t0 = time.time()             # mesmo relógio para mensagens e pacotes


def _broadcast(event):
    data = json.dumps(event)
    with _clients_lock:
        for q in _clients:
            q.put(data)


def _ms_since_start(epoch):
    return round((epoch - _t0) * 1000, 1)


def publish(proto, seq, interval):
    """Chamado pelas threads do receptor a cada mensagem recebida (camada 7)."""
    _broadcast({
        "kind": "msg",
        "proto": proto,
        "seq": seq,
        "interval": round(interval, 1),
        "t": _ms_since_start(time.time()),
    })


# ---------------------------------------------------------------- captura

def _first(value):
    return value.split("|")[0] if value else ""


def _messages_in(payload_hex):
    """Lê os números de sequência das mensagens (formato do receiver) dentro do payload."""
    if not payload_hex:
        return []
    data = bytes.fromhex(_first(payload_hex).replace(":", ""))
    usable = len(data) - len(data) % receiver.SIZE
    return [seq for seq, _ in struct.iter_unpack(receiver.FORMAT, data[:usable])]


def _parse_packet(line):
    cols = line.rstrip("\r\n").split("\t")
    if len(cols) < len(TSHARK_FIELDS):
        return None
    f = dict(zip(TSHARK_FIELDS, cols))
    is_tcp = bool(f["tcp.srcport"])
    sport = int(_first(f["tcp.srcport"] or f["udp.srcport"]) or 0)
    dport = int(_first(f["tcp.dstport"] or f["udp.dstport"]) or 0)
    letters = set(_first(f["tcp.flags.str"]))
    flags = [name for name in FLAG_ORDER if name in {TCP_FLAGS[c] for c in letters if c in TCP_FLAGS}]
    if is_tcp:
        length = int(_first(f["tcp.len"]) or 0)
        msgs = _messages_in(f["tcp.payload"])
    else:
        length = max(0, int(_first(f["udp.length"]) or 8) - 8)  # tira os 8 bytes do cabeçalho UDP
        msgs = _messages_in(f["udp.payload"])
    notes = [n.strip().lstrip("\\") for n in f["_ws.expert.message"].split("|") if n.strip()]
    return {
        "kind": "pkt",
        "proto": "TCP" if is_tcp else "UDP",
        "t": _ms_since_start(float(f["frame.time_epoch"])),
        "src": _first(f["ip.src"]), "dst": _first(f["ip.dst"]),
        "sport": sport, "dport": dport,
        "toReceiver": dport in (receiver.PORT_TCP, receiver.PORT_UDP),
        "flags": flags,
        "seq": int(_first(f["tcp.seq"]) or 0) if is_tcp else None,
        "ack": int(_first(f["tcp.ack"]) or 0) if is_tcp else None,
        "len": length,
        "frameLen": int(_first(f["frame.len"]) or 0),
        "msgs": msgs,
        "notes": notes,
    }


def capture_packets():
    """Roda o tshark e publica cada pacote das portas do experimento."""
    capture_filter = f"tcp port {receiver.PORT_TCP} or udp port {receiver.PORT_UDP}"
    cmd = [TSHARK, "-i", CAPTURE_INTERFACE, "-l", "-n", "-f", capture_filter,
           "-T", "fields", "-E", "separator=/t", "-E", "aggregator=|", "-E", "occurrence=a"]
    for field in TSHARK_FIELDS:
        cmd += ["-e", field]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
    except FileNotFoundError:
        print(f"[captura] tshark não encontrado em {TSHARK}; o painel segue sem a lista de pacotes.")
        return
    atexit.register(proc.terminate)
    for line in proc.stdout:
        try:
            packet = _parse_packet(line)
        except ValueError:
            continue
        if packet:
            _broadcast(packet)
    print("[captura] o tshark encerrou; veja a mensagem dele acima.")


# ---------------------------------------------------------------- web

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._send_page()
        elif self.path == "/events":
            self._stream_events()
        else:
            self.send_error(404)

    def _send_page(self):
        body = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        q = queue.Queue()
        with _clients_lock:
            _clients.append(q)
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    self.wfile.write(f"data: {event}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # mantém a conexão viva
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # a aba foi fechada
        finally:
            with _clients_lock:
                _clients.remove(q)

    def log_message(self, *args):
        pass  # não polui o terminal com cada requisição


def run_forever(fn):
    """Roda uma função do receptor de novo a cada teste."""
    while True:
        try:
            fn()
        except Exception:
            traceback.print_exc()
            time.sleep(1)


if __name__ == "__main__":
    if not hasattr(receiver, "on_message"):
        raise SystemExit("receiver.py ainda não tem a variável on_message (veja o topo deste arquivo).")

    receiver.on_message = publish
    for fn in (receiver.receive_tcp, receiver.receive_udp):
        threading.Thread(target=run_forever, args=(fn,), daemon=True).start()
    threading.Thread(target=capture_packets, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler)
    print(f"Painel em http://localhost:{HTTP_PORT}  (Ctrl+C para sair)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
