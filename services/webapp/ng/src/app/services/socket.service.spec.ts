import { Subject } from 'rxjs';

import { SocketService } from './socket.service';

/** A socket.io-client double: records handlers, emits and connection state. */
class FakeIoSocket {
  handlers: Record<string, ((...args: any[]) => void)[]> = {};
  emitted: any[][] = [];
  active = true;
  connectCalls = 0;
  disconnectCalls = 0;
  removedAll = false;

  on(event: string, handler: (...args: any[]) => void) {
    (this.handlers[event] ||= []).push(handler);
    return this;
  }
  off(event: string, handler?: (...args: any[]) => void) {
    this.handlers[event] = (this.handlers[event] || []).filter(h => handler !== undefined && h !== handler);
    return this;
  }
  emit(...args: any[]) { this.emitted.push(args); return this; }
  connect() { this.connectCalls++; this.active = true; return this; }
  disconnect() { this.disconnectCalls++; this.active = false; return this; }
  removeAllListeners() { this.removedAll = true; this.handlers = {}; return this; }
  fire(event: string, ...args: any[]) { (this.handlers[event] || []).forEach(h => h(...args)); }
}

describe('SocketService', () => {
  let service: SocketService;
  let socket: FakeIoSocket;
  let ioOptions: any;
  let auth: any;
  const loggedOut$ = new Subject<void>();

  beforeEach(() => {
    socket = new FakeIoSocket();
    auth = { user_id: 'alice', token: 'tok-1' };
    const userService: any = { loggedOut$, getSocketAuth: () => auth };
    service = new SocketService(userService);
    // the connection factory: the real one opens a network socket
    spyOn<any>(service, 'connect').and.callFake(function (this: SocketService) {
      if (!this['socket']) {
        this['socket'] = socket as any;
        ioOptions = { auth: (cb: any) => cb(userService.getSocketAuth()) };
        // mirror what the real connect() registers
        socket.on('connect', () => {
          if (this['connectedOnce']) { for (const room of this['rooms']) socket.emit('join', room); }
          this['connectedOnce'] = true;
        });
        socket.on('connect_error', (error: Error) => { if (/rejected/i.test(error.message)) socket.disconnect(); });
      } else if (!socket.active) {
        socket.connect();
      }
      return socket;
    });
    spyOn(console, 'warn');
  });

  it('reads the credentials at each connection attempt', () => {
    service.join('alice');
    let sent: any;
    ioOptions.auth((data: any) => sent = data);
    expect(sent).toEqual({ user_id: 'alice', token: 'tok-1' });
    auth = { user_id: 'bob', token: 'tok-2' };  // a new session
    ioOptions.auth((data: any) => sent = data);
    expect(sent).toEqual({ user_id: 'bob', token: 'tok-2' });
  });

  it('joins now and rejoins its rooms after a reconnection only', () => {
    service.join('alice');
    service.join('job-1');
    expect(socket.emitted).toEqual([['join', 'alice'], ['join', 'job-1']]);
    socket.fire('connect');  // the first connection: the joins above are already queued
    expect(socket.emitted.length).toBe(2);
    socket.fire('connect');  // a reconnection: the server forgot the rooms
    expect(socket.emitted.slice(2)).toEqual([['join', 'alice'], ['join', 'job-1']]);
    service.leave('job-1');
    expect(socket.emitted.at(-1)).toEqual(['leave', 'job-1']);
    socket.fire('connect');
    expect(socket.emitted.slice(-1)).toEqual([['join', 'alice']]);
  });

  it('removes only the handler it is given', () => {
    const mine = service.on('job_status', () => {});
    const theirs = service.on('job_status', () => {});
    service.off('job_status', mine);
    expect(socket.handlers['job_status']).toEqual([theirs]);
  });

  it('closes the connection and forgets the rooms on logout', () => {
    service.join('alice');
    loggedOut$.next();
    expect(socket.disconnectCalls).toBe(1);
    expect(socket.removedAll).toBeTrue();
    expect(service.getSocket()).toBeUndefined();
    expect(service.socketInitiated).toBeFalse();
  });

  it('stops retrying when the server refuses the credentials, and reconnects on the next join', () => {
    service.join('alice');
    socket.fire('connect_error', new Error('Connection rejected by server'));
    expect(socket.disconnectCalls).toBe(1);
    service.join('job-1');
    expect(socket.connectCalls).toBe(1);
  });

  it('ignores empty room names', () => {
    service.join('');
    service.leave(undefined as any);
    expect(socket.emitted).toEqual([]);
  });
});
