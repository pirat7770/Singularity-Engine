import socket


class PortAllocator:
    def __init__(self, start=1212, limit=200):
        self.start = start
        self.limit = limit
        self.reserved = set()

    def is_port_in_use(self, port):
        """Проверяет, занят ли UDP-порт (Robust/Lidgren использует UDP)."""
        for family, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            sock = socket.socket(family, socket.SOCK_DGRAM)
            try:
                sock.bind((addr, port))
            except OSError:
                return True
            finally:
                sock.close()
        return False

    def allocate(self):
        """Возвращает свободный UDP-порт и резервирует его."""
        for port in range(self.start, self.start + self.limit):
            if port not in self.reserved and not self.is_port_in_use(port):
                self.reserved.add(port)
                return port
        return None

    def release(self, port):
        """Снимает резервирование с порта."""
        self.reserved.discard(port)