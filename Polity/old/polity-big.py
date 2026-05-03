#!/usr/bin/python3
#508 bytes is the max payload size for a single UDP packet
from uuid import uuid4
import socket
from typing import Callable
from threading import Thread
from queue import Queue


IP_ADDRESS = '239.192.1.100'
PORT_NUMBER = 4242 # 8079 would be ASII 'PO'
TTL = 20
UUID = uuid4()
BUFFER_SIZE = 1024
UTF8 = 'utf-8'

# msg = {to,
#        from,
#        protocol_version,
#        payload,
#        checksum,


# }

def background(job_func: Callable, *args, **kwargs):
    thread = None
    try:
        thread = Thread(target=job_func, daemon=True, *args, **kwargs)
        thread.start()
    except Exception as e:
        print(e)
    return thread

class Polity():
    """Houses the send and receive methods that are used to communicate
    in a Polity. May eventually house some Polity maintenance functions. """
    def __init__(self, callback=None, queue=None, address=IP_ADDRESS, port=PORT_NUMBER, ttl=TTL):
        self.callback = callback
        self.address = address
        self.port = port
        self.ttl = ttl

        # Create the send socket.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Make the socket multicast-aware, and set TTL.
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl) # Change TTL (=20) to suit
        self.send_socket = s

        # Create the recieve socket.
        r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set some options to make it multicast-friendly
        r.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
                r.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
                pass # Some systems don't support SO_REUSEPORT
        r.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_TTL, self.ttl)
        r.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 1)
        # Bind to the port
        r.bind(('', self.port))
        # Set some more multicast options
        intf = socket.gethostbyname(socket.gethostname())
        r.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF, socket.inet_aton(intf))
        r.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP,
                     socket.inet_aton(self.address) + socket.inet_aton(intf))
        self.receive_socket = r

        self.receive_queue = queue if queue else Queue()
        self.receive_thread = background(self.listener)


    def send(self, data):
        self.send_socket.sendto(self.pack(data), (self.address, self.port))

    def receive(self):
        bytes, sender_addr = self.receive_socket.recvfrom(BUFFER_SIZE)
        data = self.unpack(bytes)
        return data

    def pack(self, data):
        "Pack up the data as if it were going on a long trip"
        return data.encode(UTF8)

    def unpack(self, data):
        "Unpack the data to be useful to the caller."
        return data.decode(UTF8)

    def enter(self):
        # Create the standard anounce message.
        self.send('Et in Arcadia, ego.')

    def listener(self):
        while True:
            print('Listening...')
            data = self.receive() # Blocks
            print(data)
            self.receive_queue.put(data)
            if self.callback:
                self.callback(data)

    def leave():
        self.send_socket.close()
        self.receive_socket.setsockopt(socket.SOL_IP, socket.IP_DROP_MEMBERSHIP,
                     socket.inet_aton(addr) + socket.inet_aton('0.0.0.0'))
        self.receive_.close()


def self_test():
    p = Polity()
    import time
    while True:
        p.enter()
        time.sleep(1)
        print('looping')
    # p.enter()
    # p.send('Is this thing on?')
    # time.sleep(300)
    print('Done.')

if __name__ == '__main__':
    import sys

    self_test()
