import { Injectable } from '@angular/core';
import { io, Socket } from "socket.io-client";
import { SOCKETIO_URL } from '../utils';
import { UserService } from './user.service';

@Injectable({
  providedIn: 'root'
})
export class SocketService {
  private socket : Socket;
  public socketInitiated = false;


  constructor(private userService: UserService) { }

  join(id: string) {
    if(!this.socketInitiated) {
      // send credentials on the handshake so the server authenticates us
      this.socket = io(SOCKETIO_URL, { auth: this.userService.getSocketAuth() });
      this.socketInitiated = true;
      this.socket.emit('connection');
    }
    this.socket.emit('join', id);
  }

  getSocket() {
    return this.socket;
  }

  disconnectSocket() {
    if (this.socket) {
      this.socketInitiated = false;
      this.socket.close();
    }
  }
}
