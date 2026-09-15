import { Injectable, OnDestroy } from '@angular/core';
import { io, Socket } from 'socket.io-client';
import { Subscription } from 'rxjs';
import { SOCKETIO_URL } from '../utils';
import { UserService } from './user.service';

export type SocketHandler = (...args: any[]) => void;

/**
 * The one Socket.IO connection of the app.
 *
 * Components join rooms and register their own handlers, and undo exactly
 * that when destroyed: `socket.off(event)` used to remove every component's
 * listener for the event and `disconnectSocket()` closed the connection for
 * everybody. The handshake credentials are read on every (re)connection, and
 * logout closes the connection so the next user does not inherit the
 * previous one's rooms.
 */
@Injectable({
  providedIn: 'root'
})
export class SocketService implements OnDestroy {
  private socket: Socket | undefined;
  private readonly rooms = new Set<string>();
  private connectedOnce = false;
  private readonly logoutSubscription: Subscription;

  constructor(private userService: UserService) {
    this.logoutSubscription = this.userService.loggedOut$.subscribe(() => this.disconnect());
  }

  ngOnDestroy(): void {
    this.logoutSubscription.unsubscribe();
    this.disconnect();
  }

  /** Whether a connection exists (or is being established). */
  get socketInitiated(): boolean {
    return this.socket !== undefined;
  }

  private connect(): Socket {
    if (!this.socket) {
      this.socket = io(SOCKETIO_URL, {
        // a function: evaluated on every connection attempt, so the current
        // session's credentials are sent (they used to be captured once)
        auth: (cb) => cb(this.userService.getSocketAuth()),
      });
      this.socket.on('connect', () => {
        if (this.connectedOnce) {
          // a reconnection: the server forgot our rooms
          for (const room of this.rooms) {
            this.socket.emit('join', room);
          }
        }
        this.connectedOnce = true;
      });
      this.socket.on('connect_error', (error: Error) => {
        console.warn('socket connection failed:', error.message);
        // refused by the server (no valid credential): do not retry in a loop,
        // the next join() reconnects with whatever credentials exist then
        if (/rejected/i.test(error.message)) {
          this.socket.disconnect();
        }
      });
    } else if (!this.socket.active) {
      this.socket.connect();
    }
    return this.socket;
  }

  /** Join a room (a user id, job id or template id); rejoined after a reconnection. */
  join(room: string) {
    if (!room) {
      return;
    }
    this.rooms.add(room);
    this.connect().emit('join', room);
  }

  leave(room: string) {
    if (!room) {
      return;
    }
    this.rooms.delete(room);
    this.socket?.emit('leave', room);
  }

  /** Register a handler; keep the reference to remove it with off(). */
  on(event: string, handler: SocketHandler): SocketHandler {
    this.connect().on(event, handler);
    return handler;
  }

  /** Remove one handler, leaving the other components' handlers in place. */
  off(event: string, handler: SocketHandler) {
    this.socket?.off(event, handler);
  }

  getSocket(): Socket | undefined {
    return this.socket;
  }

  /** Close the connection and forget the rooms (logout). */
  disconnect() {
    this.rooms.clear();
    this.connectedOnce = false;
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.disconnect();
      this.socket = undefined;
    }
  }
}
