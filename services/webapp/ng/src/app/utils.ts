export const SERVER_URL = '/api/';
export const SOCKETIO_URL = '/';

// export const SERVER_URL = "http://localhost:5000/";
// export const SOCKETIO_URL = "http://localhost:7000/";

// the roles, statuses and output keys shared with the Python services live in
// generated/rmn-contracts.ts (rendered by services/common/rmn_common/typescript.py)
export { UserRole as Role } from './generated/rmn-contracts';
