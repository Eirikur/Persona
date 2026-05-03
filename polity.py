#!/usr/bin/python3
# 508 bytes is the msgax payload size for a single UDP packet
# "Check the Polity name."
# "If this message is a CQ, save the time it was sent and time out if no responses are seen."
# How do we give up (no responses) and inform the user when trying to start?
# Backup the databases.
# Could send scheduled jobs as objects, but file transfer is more general.


# "SHORT_TIMEOUT = 5, LONG_TIMEOUT = 20"

from uuid import uuid4
import socket
from typing import Callable
from threading import Thread
from queue import Queue
import struct
import json
import time
import random

# Components of this project
from message import Message
from record import Record, ConstantRecord

POLITY_VERSION = 0.1
multicast_group = ('224.3.29.71', 10000)
MULTICAST_ADDRESS = '224.3.29.71'
PORT_NUMBER = 4242 # 8079 would be ASII 'PO' FIXME This is entirely unused.
TTL = 10
UUID = uuid4()
BUFFER_SIZE = 2048
UTF8 = 'utf-8'
HTTPS_PORT = 443
WAN_TARGET = ('8.8.8.8', HTTPS_PORT) # Google name service. This needs to be up.
MAX_MESSAGE_LENGTH = 65507 # UDP max bytes

newline = '\n'


def background(job_func: Callable, *args, **kwargs):
    "Call a function that runs in its own thread."
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
    roles = frozenset(['CMD_LINE', 'UI', 'BRAIN', 'SOUND', 'DIALOG'])
    system_messages = (['CQ', 'IAM', 'RESEND', # Not exposed to clients.
                        'RELOAD', 'BADID', 'ACK', 'NAK'])
    msg_types = ['PLAY', 'CMD', 'SYS', 'DIALOG']
    def __init__(self, name='Polity', simple=False, callback=None, queue=None,
                 multicast_address=MULTICAST_ADDRESS, port=PORT_NUMBER,
                 ttl=TTL, role=None, monitor=False):
        self.polity_version = POLITY_VERSION
        self.polity = name
        self.role = role
        self.id = str(uuid4())
        self.ip = self.ip_address()
        self.multicast_address = multicast_address
        self.port = port
        self.ttl = struct.pack('b', ttl)
        self.sequence_number = 0
        self.monitor = monitor

        if callback:
            self.callback = callback
            self.listener = self.listener_callback
        else:
            self.queue = queue if queue else Queue() # Accept passed queue or create one.
            self.replies = Queue()
            self.listener = self.listener_queue
            self.get = self.queue.get


        # Create the send socket.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Tell the operating system to add the socket to the multicast group
        # on all interfaces.
        group = socket.inet_aton(self.multicast_address)
        mreq = struct.pack('4sL', group, socket.INADDR_ANY)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Re-use address.
        # Make the socket multicast-aware, and set TTL.
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl) # Change TTL (=20) to suit
        # Bind to the server address
        server_address = ('', 10000)
        s.bind(server_address)
        self.send_socket = s
        self.receive_socket = s # If this works, it's simpler.
        self.timestamp = str(round(time.time(),2))
        if not simple: # Simple mode does nothing in background.
            self.receive_thread = background(self.listener)
            self.join_or_start_polity()
        else:
            print('Simple mode. No background actions.')

    def get_replies(self, timeout=0)->Message:
        return self.replies.get()

    def _send(self, msg):
        self.sequence_number += 1 # Increment. This is the one place it happens.
        msg['my_number'] = self.sequence_number
        msg['timestamp'] = str(round(time.time(),2))
        try:
            packed_msg = self.pack(msg)
        except Exception as e:
            print(f"In polity._send: {e}")
            print('bad pack/unpack')
            return None
            if len(packed_msg) > MAX_MESSAGE_LENGTH:
                self.send_long_message(msg)
        else:
            self.send_socket.sendto(bytes(packed_msg, 'utf-8'),
                                    multicast_group)

    def _receive(self):
        data, sender_addr = self.receive_socket.recvfrom(BUFFER_SIZE)
        msg = self.unpack(data)

        return self.message_handler(msg)

    def send_long_message(self, msg:str)->bool:
        print('send_long_message: NOT IMPLEMENTED')
        return 1/0

    def message(self, body, type='CMD', reply_to='')->dict:
        """Method for clients to call to get a Message object,
           pre-populated with useful default values."""
        msg =  {
            'version':    self.polity_version,
            'polity':     self.polity,
            'type':       type, # Defaults to CMD from the arguments.
            'from':      self.id,
            'from_ip':    self.ip,
            'my_number':  self.sequence_number,
            'body_len':   len(body),
            'body':       body
        }
        return Message(msg)


    def send_cmd(self, text:str):
        msg = self.message(text)
        self._send(msg)


    def reply(self, input_msg, text, status=True): # Reply to msg with text.
        """Method for clients to call to reply to a message.
           The input msg is the message we want to reply to."""
        m =  { # msg.foo below is a field from the message we are replying to.
            'polity':     self.polity, # Could be the sender message polity.
            'type':       'REPLY',
            'to':         input_msg['from'],
            'from':       self.id,
            'from_ip':    self.ip,
            'reply_to':   input_msg.my_number, # Outgoing number supplied in _send()
            'body_len':   len(text),
            'body':       text,
            'body_checksum': 0
        }
        input_msg.update(m)
        self._send(input_msg)

    def announce(self)->None:
        msg =  {
            'version':    self.polity_version,
            'polity':     self.polity,
            'type':       'IAM',
            'from':       self.id,
            'from_ip':    self.ip,
            'my_number':  self.sequence_number
        }
        self._send(msg)

    def join_or_start_polity(self)->None:
        """At the moment, all this is doing is sending an announcement.
        """
        msg =  {
            'version':    self.polity_version,
            'polity':     self.polity,
            'type':       'CQ',
            'to':      '',
            'from':    self.id,
            'from_ip':    self.ip,
            'my_number':  0, # Filled-in by _send()
            'timestamp': ''
        }
        self._send(msg)

    def ip_address(self)->str:
        # def ip_addresses()->dict:
        #     "Returns [ip4 address, ip6 address]"
        #     addresses = []
        #     for protocol in [socket.AF_INET, socket.AF_INET6]:
        #         with socket.socket(protocol, socket.SOCK_DGRAM) as sock:
        #             sock.connect(WAN_TARGET)
        #             addresses.append(sock.getsockname()[0])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(WAN_TARGET)
            return(sock.getsockname()[0])

    def send_text(self, text:str):
        msg = self.message(text)
        self._send(msg)


    def print_values(self, label:str, msg:dict)->None:
        m = [str(msg[key])[-16:] for key in msg if msg[key]]
        m = ' '.join(m)
        print(f"{label} {m}")

    def pack(self, msg:dict):
        "Pack up the data as if it were going on a long trip."
        msg = {key:value for (key, value) in msg.items() if value} # Strip null items
        packed = json.dumps(msg, indent=4)
        return packed
        # return bytes(packed, 'utf-8')

    def unpack(self, data):
        "Unpack the data to be useful to the caller."
        unpacked = "UnPacked"


        try:
            unpacked = json.loads(data)
        except Exception as e:
            print(f"polity.unpack: {e}")
            unpacked = f"Failed to unpack {len(data)} byte message. Check Polity buffer size."
            print()
            text = data.decode('utf-8').split(newline)
            for line in text:
                print(line)
            print()

        return unpacked

    def doesnt_concern_us(self, msg)->bool:
        """Filter out messages we sent, and messages from other polities."""
        if msg['from'] == self.id or msg.polity != self.polity: # This message does not concern us.
            return True
        else:
            # print(f"Concerns us: {msg['body']}")
            return False

    def listener_queue(self)->None:
        """
        This is bypassing message_handler() right now FIXME
        Blocking loop that receives messages and puts them into queues.
        Filtering seems reasonable here. It simplifies the clients.
        """
        while True:
            msg = self._receive() # Blocks
            if msg:
                if self.monitor:
                    self.print_values('R:', msg)
                if self.doesnt_concern_us(msg):
                    print(f"Not for us: from {msg['from']} our polity {self.polity} our id {self.id}")
                    continue
                self.queue.put(msg)
                if msg.type == 'REPLY': # Replies can be 'to' or broadcast now.
                    if 'to' in msg:
                        if msg.to != self.id: # It's sent to another node.
                            continue #
                        self.replies.put(msg)

    # def listener_callback(self):
    #     # This looks wrong. Was never tested. FIXME
    #     self.callback(self._receive())

    def leave(self)->None:
        self._send('BYE') # Something more formal?
        self.send_socket.close()

    def message_handler(self, msg):
        # Requires entire redesign.

        msg = Message(msg)
        if msg['from'] == self.id:
                return None
        if self.monitor:
            self.print_values('R:', msg)
        if msg.polity != self.polity: #
            print(f"Recieved message from another polity: {msg.polity}")  # FIXME
            print('Write some code to cope with this.') # TODO
            # # If this is from a different polity:
            #     # If we have no other members:
            #         # Change our polity name.
            #         self.polity = msg.polity
            #         self.timestamp = time.time()
            #         self.announce()
            #         return None
            # else: # There's another node using this uuid4 id value!
            #     print('BAD ID because duplicate.')
            #     self.id = str(uuid4()) # Change our ID.
        # signifier = msg.role if 'role' in msg else msg['from']
        # Real work starts here. Polity-private messages maintain the polity.
        if msg.type in self.system_messages:
            # print(f"System message {msg.type}")
            if msg.type == 'CQ':
                background(self.pause_then_announce)
                return None
        else: # Not a system message, must be a client message.
            return msg



    def pause_then_announce(self):
        random.seed()
        time.sleep(2 * random.random()) # Up to two seconds
        self.announce()


def self_test():  # self-test should not be a system message! FIXME
    p = Polity()
    print(f"id: {p.id}")
    print()
    p.send_text('Watson, I want you.')
    while True:
        msg = Message(p.get())
        print(f"Received: {msg.type} from {msg['from']}.")


if __name__ == '__main__':
    self_test()
