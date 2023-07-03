import pickle

class PickleDict:
    def __init__(self, file_path, autocommit=False):
        self.file_path = file_path
        self.autocommit = autocommit
        self.data = self.load_dict()

    def load_dict(self):
        try:
            with open(self.file_path, 'rb') as file:
                loaded_data = pickle.load(file)
        except FileNotFoundError:
            loaded_data = {}
        except EOFError:
            loaded_data = {}

        return loaded_data

    def save_dict(self):
        with open(self.file_path, 'wb') as file:
            pickle.dump(self.data, file)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        if self.autocommit:
            self.save_dict()

    def __delitem__(self, key):
        del self.data[key]
        if self.autocommit:
            self.save_dict()

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def items(self):
        return self.data.items()
    
    def clear(self):
        self.data.clear()
        if self.autocommit:
            self.save_dict()
