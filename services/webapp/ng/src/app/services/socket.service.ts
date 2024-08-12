import { Injectable } from '@angular/core';
import { io, Socket } from "socket.io-client";
import { SOCKETIO_URL } from '../utils';

@Injectable({
  providedIn: 'root'
})
export class SocketService {
  private socket : Socket;
  public socketInitiated = false;


  constructor() { }

  join(id: string) {
    if(!this.socketInitiated) {
      this.socket = io(SOCKETIO_URL);
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
