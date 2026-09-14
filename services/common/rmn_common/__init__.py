"""Contracts shared by the RMN server and executor.

Everything here is part of the wire format between the services (MongoDB
documents, the storage tree on the NFS share, csv columns). Change a value
here and both services follow; that is the point of the package.
"""

__version__ = "0.1.0"
