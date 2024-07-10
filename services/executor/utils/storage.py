import os
import shutil
from pathlib import Path


# either service root or project root depending on the environment
ROOT_DIR = Path(__file__).resolve().parent.parent
if os.getenv("ENVIRONMENT") != "production":
    ROOT_DIR = ROOT_DIR.parent.parent


def create_tree(file_path):
    split = file_path.rsplit(os.sep, 1)
    os.makedirs(split[0], exist_ok=True)


# use this method to avoid Invalid cross-device link error
# https://stackoverflow.com/questions/42392600/oserror-errno-18-invalid-cross-device-link
# shutil.move() seems to not detect the different filesystem
def move(old_file, new_file):
    shutil.copy(old_file, new_file)
    os.remove(old_file)


class Storage:
    def __init__(self, storage_path=None):
        if storage_path:
            self.path = Path(storage_path)
        elif os.getenv('STORAGE'):
            self.path = Path(os.getenv('STORAGE'))
        else:
            self.path = ROOT_DIR.joinpath("storage")
        print("Storage path is: ", self.path)

    def abs_path(self, r_path):
        abs_p = os.path.join(str(self.path), r_path)
        # abs_p =f'/Executor/storage/{r_path}'
        return str(abs_p)

    def move_to(self, l_file, s_file):
        s_abs_file = self.abs_path(s_file)
        create_tree(s_abs_file)
        move(l_file, s_abs_file)

    def copy_from(self, s_file, l_file):
        s_abs_file = self.abs_path(s_file)
        create_tree(l_file)
        shutil.copy(s_abs_file, l_file)

    def remove(self, s_file):
        os.remove(self.abs_path(s_file))

    def remove_tree(self, s_dir):
        shutil.rmtree(self.abs_path(s_dir))
