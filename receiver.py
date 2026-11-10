import socket
import threading
import struct, time
PORT_TCP = 5001
PORT_UDP = 5002
FORMAT = "!IQ"
SIZE = struct.calcsize(FORMAT)
on_message= None

def recv_exact(conn, n):
    """ Le exatamente n bytes do fluxo TCP. Devolve None se a conexão fechar """
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf)) # pede só o que falta
        if not chunk:
            return None
        buf += chunk
    return buf

def receive_tcp():    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("", PORT_TCP)) # "" = SERVE PARA PEGAR TODAS AS INTERFACES DE REDE 
        server.listen()
        print("(TCP) Aguardando na Porta...")

        conn, addr = server.accept() # bloqueia até alguem conectar
        with conn:
            print("(TCP) Conexão de", addr)
            previous = None
            count = 0
            while True:
                data = recv_exact(conn, SIZE)
                if data is None:
                    break

                seq, sent_ns = struct.unpack(FORMAT, data)
                now = time.perf_counter()
                interval = 0.0 if previous is None else ( now - previous ) * 1000
                previous = now 
                count += 1 
                print(f"(TCP) seq={seq:3d}  intervalo={interval:6.1f} ms")
                if on_message:
                    on_message("TCP", seq, interval)
            print(f"(TCP) fim: {count} mensagens recebidas")


def receive_udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("", PORT_UDP))
        print("(UDP) Aguardando na Porta...")
        previous = None
        count = 0
        while True:
            try:
                data, addr = server.recvfrom(1024)
            except socket.timeout:
                break
            server.settimeout(5)
            seq, sent_ns = struct.unpack(FORMAT, data)
            now = time.perf_counter()
            interval = 0.0 if previous is None else ( now - previous ) * 1000
            previous = now 
            count += 1 
            print(f"(UDP) seq={seq:3d}  intervalo={interval:6.1f} ms")
            if on_message:
                on_message("UDP", seq, interval)
        print(f"(UDP) fim: {count} mensagens recebidas")

if __name__ == "__main__":
    t1 = threading.Thread(target=receive_tcp)
    t2 = threading.Thread(target=receive_udp)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
