export const SERVER_URL = '/api/';

/** Special characters accepted in a password (the server's list: the classical
 *  set Bitwarden generates plus . ? _ -). The key filter of the password
 *  dialogs is built from it. */
export const PASSWORD_SPECIAL_CHARACTERS = '!@#$%^&*.?_-';
export const PASSWORD_CHARACTER_REGEX = new RegExp(
  '^[a-zA-ZÀ-ÿ0-9' + PASSWORD_SPECIAL_CHARACTERS.replace(/[\\\]^-]/g, '\\$&') + ']+$');
/** Same bounds as the server (user_service.MIN/MAX_PASSWORD_LENGTH). */
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 32;

/** Why a password would be refused by the server, or undefined when it is
 *  acceptable: the dialogs check before sending so the user gets the reason
 *  in French, the server checks again. */
export function passwordError(password: string): string | undefined {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `Veuillez entrer au minimum ${PASSWORD_MIN_LENGTH} caractères!`;
  }
  if (password.length > PASSWORD_MAX_LENGTH) {
    return `Veuillez entrer au maximum ${PASSWORD_MAX_LENGTH} caractères!`;
  }
  if (!PASSWORD_CHARACTER_REGEX.test(password)) {
    return `Caractères permis: lettres, chiffres et ${PASSWORD_SPECIAL_CHARACTERS.split('').join(' ')}`;
  }
  return undefined;
}
export const SOCKETIO_URL = '/';

// export const SERVER_URL = "http://localhost:5000/";
// export const SOCKETIO_URL = "http://localhost:7000/";

// the roles, statuses and output keys shared with the Python services live in
// generated/rmn-contracts.ts (rendered by services/common/rmn_common/typescript.py)
export { UserRole as Role } from './generated/rmn-contracts';
