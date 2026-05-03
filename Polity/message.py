# message.py, The message for the Polity networking system.
# 27 Jan 2022
from record import Record #, ConstantRecord

msg =  {
    'version':    '',
    'polity':     '',
    'type':       '',
    'to':         '',
    'from':       '',
    'my_number':  0,
    'timestamp':  '',
    'reply_to':   0,
    'body_len':   0,
    'body': '',
    'body_checksum': 0,
    'continued': False,
    'packets': 0

}

class Message(Record):
    """Record does all the magic of preventing new keys,
    and type-checking against the default values."""
    __delattr__ = dict.__delitem__
    def __init__(self, source_dict={}):
        if not isinstance(source_dict, dict):
            print(f"source_dict: {source_dict}, type: {type(source_dict)}")
            raise ValueError
        self.update(msg) # Template above
        self.update(source_dict) # Must be a dict, empty is okay.

class Body(Record):
    """This is the body for replies from the J brain server,
       which can be multiline and it's useful to have a status field
       so that a client doesn't have to parse the text that is returned.
    """
    def __init__(self)->None:
        self.text = ''
        self.status = False
