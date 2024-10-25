import os
import sys

parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, parent_dir)


from process_copy.parser import parser, run_args


if __name__ == "__main__":
    args = parser.parse_args()
    run_args(args)
