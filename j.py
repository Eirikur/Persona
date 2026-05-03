#!/usr/bin/python3
"""July 2021 An incarnation of the Jeeves idea. Intended to be extensible.
Runs as a service, running its services as threads or subprocesses.
Listens via nng."""

# use the atexit module to shut down things like profiling before exit()

# Fix: manage to use bidirectional sockets. 17 Nov. 2021`

# Add:
#    Get modified/created date.
#    Async check in sched loop? and reload.

#    New daemon watches files and moves them.

#    Reload on hard crash exit for development.
def this(thing)->bool:
    pass
import sys
import os
import time
import logging
import traceback
import socket
import ipaddress

# from typing import Callable, Iterable
import cProfile, pstats, io
from pstats import SortKey
pr = cProfile.Profile()
pr.active = False # My own attribute.

# Third Party
# import extended_exec_formatter

# part of this program
import jt
from jt import alert # Scheduler needs this???
from networking.udp import udp_receive, udp_broadcast

log_file_name = '/home/eh/Projects/j/j.log'
history_file = '/home/eh/Projects/j/history.log'

newline = '\n'
space = ' '
reply_encoding = {True: '1', False: '0'}

sockets_to_clean_up = [server_socket, sender_socket]
for socket in sockets_to_clean_up:
    try:
        os.remove(socket)
    except OSError as e:
        print("Socket file is not present.")
    except Exception as e:
        print(e)
        sys.exit(1)

def set_up_logging(dbg: bool=False):
    "docstring"
    # w%(filename)s Filename portion of pathname.
    # %(module)s Module (name portion of filename).
    # %(funcName)s Name of function containing the logging call.
    # %(lineno)d Source line number where the logging call was issued (if available).

    # Hack to make these aliases available despite
    # setting up logging in a function scope.
    global log, debug, info, error
    log = logging.getLogger('J')
    log.setLevel(logging.INFO);
    debug = log.debug
    info = log.info
    error = log.error

    # if dbg:
    #     formatter = extended_exec_formatter.ExtendedExceptionFormatter('%(asctime)s %(levelname)s - %(message)s')
    #     extended_exec_formatter.install_exec_handler()
    #     print('Extended logging is active.')
    # else:
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(filename)s %(funcName)s %(lineno)d - %(message)s')

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    log.addHandler(console)

    file = logging.FileHandler(log_file_name)
    file.setLevel(logging.INFO)
    file.setFormatter(formatter)
    log.addHandler(file)

    return log
    
log = set_up_logging(dbg=False)


                
def udp_receiver_loop()->None:
    while True:
        msg = None
        try:
            msg = udp_receive() # Blocking UDP receive.
        except Exception as e:
            error(f"Receive error. {e}")
            exit()
            continue
        else:
            if len(msg):
                handle_request(msg)
            else:
                print('Empty message!')

def reply(msg: str)->None:
    print(f"Reply: {msg}")
    if isinstance(msg, list):
         msg = newline.join(msg)
    # elif isinstance(msg, str):
    #     msg = msg.encode('utf-8')
    else:
        reply = f"Reply error: |{msg}| {type(msg)}"
    try:
        udp_broadcast(msg)
    except Exception as e:
        print(type(msg), msg)
        print(f"Send error. {e}")

def reload():
    """Reload updated source file..."""
    # TODO Needs to shut down any threads or processes.
    msg = 'Will reload...'
    reply(msg) # just to release the wait for the command line client 
    print(msg)
    jt.shutdown() # Shut down the scheduling system.
    print(f"Reloading from {__file__}.")
    os.execv(__file__,['nothing here'])  # Run a new iteration of the current script, providing any command line args from the current iteration.

def shutdown():
    reply("Will exit.")
    jt.shutdown()
    exit()

def profile():
    if pr.active:
        pr.disable()
        pr.active = False
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        ps.dump_stats('j-profile.dump')
        text = s.getvalue()
        print(text)
        with open('j-profile.txt', 'w') as f:
            f.write(text)
        msg = 'Profiling deactivated and profile dumped'
        print(msg)
        return(msg)
    else:
        pr.enable()
        return('Profiling enabled.')


def handle_request(msg):
    cmd, modifier, remainder = jt.get_cmd(msg)
    if cmd == 'reload':
        reload()
    elif cmd == 'profile':
        return profile()
    elif cmd == 'debug':
        set_up_logging(dbg=True)
        msg = 'Debug mode activated. This only effects logging today.'
        print(msg)
        return(msg)
    elif cmd in ['exit', 'bye', 'shutdown']:
        jt.shutdown()
        msg = 'Shutting down.'
        reply(msg)
        print(msg)
        exit()

    start = time.time()
    response=jt.command(msg)
    elapsed = 1000 * (time.time() - start)
    perf_msg = f"Performed '{msg}' in {round(elapsed, 4)} milliseconds."
    #info(perf_msg)
    print(perf_msg)

    
    with open(history_file, 'a') as f:
        f.write(newline.join([msg, response, '\n']))
                
    
    # if isinstance(response, bool):
    #     response='1' if response is True else '0'
    # if isinstance(response, bytes):
    #     response = response.decode('utf-8')
    if isinstance(response, list) or isinstance(response, tuple):
        response = newline.join(response)
    elif isinstance(response, bool):
        response = reply_encoding[response]# '0' or '1'
    elif not isinstance(response, str):
        response = f"{str(response)}\n-- Was not a string."
    reply(response)

# def debug_wrapper():
#     except Exception as e:
#         print('Oops! Top-level unhandled: ', e)
#         exception_type, exception_object, exception_traceback = sys.exc_info()
#         filename = exception_traceback.tb_frame.f_code.co_filename
#         line_number = exception_traceback.tb_lineno
#         stack_dump = traceback.format_stack()
#         msg = ['Unhandled exception. Will restart. Stack trace:']
#         reply(stack_dump)
#         print("Exception type: ", exception_type)
#         print("File name: ", filename)
#         print("Line number: ", line_number)

#         reload()





    
def main()->None:
    jt.setup() # Initialization of scheduling module.
    udp_receiver_loop()

if __name__ == '__main__':
    # main()
    set_up_logging()
    main()
    # try:
    #     # cProfile.run(main())
