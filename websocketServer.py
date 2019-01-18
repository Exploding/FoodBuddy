from SimpleWebSocketServer import WebSocket

import globals

class SimpleServer(WebSocket):
    def handleConnected(self):
        print(self.address, 'connected')
        globals.clients.append(self)

    def handleClose(self):
        globals.clients.remove(self)
        print(self.address, 'closed')