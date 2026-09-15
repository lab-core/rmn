export const SERVER_URL = '/api/';

/** Special characters accepted in a password (the server's list: the classical
 *  set Bitwarden generates plus . ? _ -). The key filter of the password
 *  dialogs is built from it. */
export const PASSWORD_SPECIAL_CHARACTERS = '!@#$%^&*.?_-';
export const PASSWORD_CHARACTER_REGEX = new RegExp(
  '^[a-zA-ZÀ-ÿ0-9' + PASSWORD_SPECIAL_CHARACTERS.replace(/[\\\]^-]/g, '\\$&') + ']+$');
export const SOCKETIO_URL = '/';

// export const SERVER_URL = "http://localhost:5000/";
// export const SOCKETIO_URL = "http://localhost:7000/";

// the roles, statuses and output keys shared with the Python services live in
// generated/rmn-contracts.ts (rendered by services/common/rmn_common/typescript.py)
export { UserRole as Role } from './generated/rmn-contracts';
