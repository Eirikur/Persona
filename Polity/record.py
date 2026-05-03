
class Record(dict):
    __getattr__ = dict.__getitem__
    __delattr__ = None # dict.__delitem__
    #    def __init__(self, *args, **kwargs):
    #         super().__init__(*args, **kwargs)
    #         self.__dict__ = self
    #         # self.__setitem__ = self.__setattr__
    # 4
    def __setattr__(self, key, value):
        if key not in [*self.keys(), '__dict__']:
            raise KeyError('No new keys allowed')
        else:
            self[key] = value


    def __setitem__(self, key, value):
        if key not in self:
            raise KeyError('No new keys allowed')
        else:
            if type(self[key]) == type(value):
                super().__setitem__(key, value)
            else:
                raise ValueError('Must match type.')

    def __missing__(self, *args, **kwargs):
        raise KeyError

class ConstantRecord(Record):
    error_msg = 'This object is immutable'
    def __setattr__(self, key, value):
        raise TypeError(self.error_msg)
    def __setitem__(self, key, value):
        raise TypeError(self.error_msg)
    def __missing__(self, *args, **kwargs):
        raise TypeError(self.error_msg)
