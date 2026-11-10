import socket 
import struct, time
import threading


FORMAT = "!IQ"
IP_RECEIVER = "" #IP DO COMPUTADOR QUE VAI ENVIAR
PORT_TCP = 5001
PORT_UDP = 5002



def send_tcp():    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.connect((IP_RECEIVER, PORT_TCP))

        for seq in range(1, 101):
            data = struct.pack(FORMAT, seq, time.time_ns())
            s.sendall(data)
            time.sleep(0.05)

def send_udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for seq in range(1, 101):
            data = struct.pack(FORMAT, seq, time.time_ns())
            s.sendto(data, (IP_RECEIVER, PORT_UDP))
            time.sleep(0.05)


if __name__ == "__main__":
    t1 = threading.Thread(target=send_tcp)
    t2 = threading.Thread(target=send_udp)
    t1.start()
    t2.start()
    t1.join()
    t2.join()