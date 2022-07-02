# coding: utf-8

import socket
import selectors
import signal
import logging
import argparse

# configure logger output format
logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',datefmt='%m-%d %H:%M:%S')
logger = logging.getLogger('Load Balancer')


# used to stop the infinity loop
done = False

sel = selectors.DefaultSelector()

policy = None
mapper = None


# implements a graceful shutdown
def graceful_shutdown(signalNumber, frame):  
    logger.debug('Graceful Shutdown...')
    global done
    done = True


# n to 1 policy
class N2One:
    def __init__(self, servers):
        self.servers = servers  

    def select_server(self):
        return self.servers[0]

    def update(self, *arg):
        pass


# round robin policy
class RoundRobin:
    def __init__(self, servers):
        self.servers = servers
        self.cursor = 0

    def select_server(self):
        server = self.servers[self.cursor]
        self.cursor = (self.cursor + 1) % len(self.servers)  
        return server
    
    def update(self, *arg):
        pass


# least connections policy
class LeastConnections:
    def __init__(self, servers):
        self.servers = servers
        self.conns = {}
        for conn in self.servers:
            self.conns[conn] = 0

    def select_server(self):
        print(self.conns)
        min = self.servers[0] 
        for conn in self.servers:
            if( self.conns[conn] < self.conns[min]): 
                min = conn
        self.conns[min] += 1
        return min

    def update(self, *arg):
        #logger.debug("DELETE: %s", arg[0].getpeername())
        self.conns[arg[0].getpeername()] -= 1


# least response time
class LeastResponseTime:
    def __init__(self, servers):
        self.servers = servers
        self.inicialTime = {}
        self.num = {}
        self.count=0
        self.avgTime = {}
        for server in servers:
            self.avgTime[server] = 0
            self.num[server] = 0
            self.inicialTime[server] = 0
        #logger.debug("init: ")

    def select_server(self):
        logger.debug("select: ")
        min = 9001
        minServer = self.servers[0]
        if self.num[0] == 0:
               for server in self.servers:
                   self.inicialTime[server] = time.time()
        for server in self.avgTime:
            #logger.debug("select: %s"+ str(self.TUMTUMTUM.get(server)/self.num.get(server)))
            if self.num.get(server) != 0:
                if self.avgTime.get(server)/self.num.get(server) < min:
                    min = self.avgTime.get(server)/self.num.get(server)
                    minServer = server
            else:
                if self.num.get(server) < min:
                    min = self.avgTime.get(server)
                    minServer = server
        self.inicialTime[minServer] = time.time()
        """
        for server in self.avgTime:
            #logger.debug("select: %s"+ str(self.TUMTUMTUM.get(server)/self.num.get(server)))
            if self.num.get(server) != 0:
                if self.avgTime.get(server)/self.num.get(server) < min:
                    min = self.avgTime.get(server)/self.num.get(server)
                    minServer = server
            else:
                if self.num.get(server) < min:
                    min = self.avgTime.get(server)
                    minServer = server
        self.inicialTime[minServer] = time.time()
        """    
        logger.debug("server %s" , minServer)  
        logger.debug("TUMTUM %s" , self.avgTime)  
        logger.debug("foseis %s" , self.inicialTime)  
        return minServer

    def update(self, *arg):
        #for server in self.servers:
            #logger.debug("server: %s", server)
        #logger.debug(arg)
        socket = arg[0].getpeername()
        addr = ('localhost',socket[1])
        if addr in self.inicialTime:
            logger.debug("addr %s" , addr)  
            self.avgTime[addr] = time.time() - self.inicialTime.get(addr) 
        logger.debug("num %s", self.avgTime.get(addr))


POLICIES = {
    "N2One": N2One,
    "RoundRobin": RoundRobin,
    "LeastConnections": LeastConnections,
    "LeastResponseTime": LeastResponseTime
}

class SocketMapper:
    def __init__(self, policy):
        self.policy = policy
        self.map = {}

    def add(self, client_sock, upstream_server):
        client_sock.setblocking(False)
        sel.register(client_sock, selectors.EVENT_READ, read)
        upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream_sock.connect(upstream_server)
        upstream_sock.setblocking(False)
        sel.register(upstream_sock, selectors.EVENT_READ, read)
        logger.debug("Proxying to %s %s", *upstream_server)
        self.map[client_sock] =  upstream_sock

    def delete(self, sock):
        sel.unregister(sock)
        sock.close()
        if sock in self.map:
            self.map.pop(sock)

    def get_sock(self, sock):
        for client, upstream in self.map.items():
            if upstream == sock:
                return client
            if client == sock:
                return upstream
        return None
    
    def get_upstream_sock(self, sock):
        return self.map.get(sock)

    def get_all_socks(self):
        """ Flatten all sockets into a list"""
        return list(sum(self.map.items(), ())) 

def accept(sock, mask):
    client, addr = sock.accept()
    logger.debug("Accepted connection %s %s", *addr)
    mapper.add(client, policy.select_server())

def read(conn,mask):
    data = conn.recv(4096)
    if len(data) == 0: # No messages in socket, we can close down the socket
        mapper.delete(conn)
    else:
        mapper.get_sock(conn).send(data)


def main(addr, servers, policy_class):
    global policy
    global mapper

    # register handler for interruption 
    # it stops the infinite loop gracefully
    signal.signal(signal.SIGINT, graceful_shutdown)

    policy = policy_class(servers)
    mapper = SocketMapper(policy)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(addr)
    sock.listen()
    sock.setblocking(False)

    sel.register(sock, selectors.EVENT_READ, accept)

    try:
        logger.debug("Listening on %s %s", *addr)
        while not done:
            events = sel.select(timeout=1)
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)
                
    except Exception as err:
        logger.error(err)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pi HTTP server')
    parser.add_argument('-a', dest='policy', choices=POLICIES)
    parser.add_argument('-p', dest='port', type=int, help='load balancer port', default=8080)
    parser.add_argument('-s', dest='servers', nargs='+', type=int, help='list of servers ports')
    args = parser.parse_args()
    
    servers = [('localhost', p) for p in args.servers]
    
    main(('127.0.0.1', args.port), servers, POLICIES[args.policy])
