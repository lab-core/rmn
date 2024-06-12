import os
import shutil
import glob
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

def create_tree(file_path):
    os.makedirs(file_path.rsplit(os.sep,1)[0], exist_ok=True)

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
            print("Storage path:", self.path)
        elif os.getenv('STORAGE'):
            self.path = Path(os.getenv('STORAGE'))
        else:
            self.path = ROOT_DIR.joinpath("storage")
        print(f"Access for {self.path}: ", os.access(self.path, os.R_OK))
        print(f"Access for {self.path}: ", os.access(self.path, os.W_OK))

    def abs_path(self, r_path):
        abs_path = str(self.path.joinpath(r_path))
        print("Generated absolute path:", abs_path)
        return abs_path

    def move_to(self, l_file, s_file):
        s_abs_file = self.abs_path(s_file)
        print("Moving from:", l_file, "to:", s_abs_file)
        if not os.path.exists(l_file):
            raise ValueError("Storage can't find local file " + l_file)
        create_tree(s_abs_file)
        move(l_file, s_abs_file)

    def copy_from(self, s_file, l_file):
        s_abs_file = self.abs_path(s_file)
        print("Attempting to copy from:", s_abs_file, "to:", l_file)
        if not os.path.exists(s_abs_file):
            raise ValueError("Storage can't find file " + s_abs_file)
        create_tree(l_file)
        shutil.copy(s_abs_file, l_file)
        print("Copy successful from:", s_abs_file, "to:", l_file)

    def remove(self, s_file):
        abs_path = self.abs_path(s_file)
        for f in glob.glob(str(abs_path)):
            os.remove(f)

    def remove_tree(self, s_dir):
        shutil.rmtree(self.abs_path(s_dir))
