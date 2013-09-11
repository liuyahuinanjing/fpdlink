import ctypes
import re
import os
import queue
import threading
import collections

_lpath = (os.path.dirname(__file__))
if _lpath == '':
    _lpath = '.'
libov =  ctypes.cdll.LoadLibrary(_lpath + "/libov.so")

class FTDI_Device(ctypes.Structure):
    _fields_ = [
                ('_1', ctypes.c_void_p),
                ('_2', ctypes.c_void_p),
                ]

pFTDI_Device = ctypes.POINTER(FTDI_Device)

# FTDIDevice_Open
FTDIDevice_Open = libov.FTDIDevice_Open
FTDIDevice_Open.argtypes = [pFTDI_Device]
FTDIDevice_Open.restype = ctypes.c_int

# FTDIDevice_Close
FTDIDevice_Close = libov.FTDIDevice_Close
FTDIDevice_Close.argtypes = [pFTDI_Device]

FTDIDevice_Write = libov.FTDIDevice_Write
FTDIDevice_Write.argtypes = [
        pFTDI_Device, # Dev
        ctypes.c_int, # Interface
        ctypes.c_char_p, # Buf
        ctypes.c_size_t, # N
        ctypes.c_bool, # async
        ]
FTDIDevice_Write.restype = ctypes.c_int

p_cb_StreamCallback = ctypes.CFUNCTYPE(
        ctypes.c_int,    # retval
        ctypes.POINTER(ctypes.c_uint8), # buf
        ctypes.c_int, # length
        ctypes.c_void_p, # progress
        ctypes.c_void_p) # userdata

FTDIDevice_ReadStream = libov.FTDIDevice_ReadStream
FTDIDevice_ReadStream.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_int,    # interface
        p_cb_StreamCallback, # callback
        ctypes.c_void_p, # userdata
        ctypes.c_int, # packetsPerTransfer
        ctypes.c_int, # numTransfers
        ]
FTDIDevice_ReadStream.restype = ctypes.c_int

FTDI_INTERFACE_A = 1
FTDI_INTERFACE_B = 2

# hack
keeper = []

class FTDIDevice:
    def __init__(self):
        self.__is_open = False
        self._dev = FTDI_Device()

    def __del__(self):
        if self.__is_open:
            self.__is_open = False
            FTDIDevice_Close(self._dev)

    def open(self):
        err = FTDIDevice_Open(self._dev)
        if not err:
            self.__is_open = True

        return err

    def write(self, intf, buf, async=False):
        if not isinstance(buf, bytes):
            raise TypeError("buf must be bytes")

        return FTDIDevice_Write(self._dev, intf, buf, len(buf), async)

    def read(self, intf, n):
        buf = []

        def callback(b, prog):
            buf.extend(b)
            return int(len(buf) >= n)

        self.read_async(intf, callback, 4, 4)

        return buf

    def read_async(self, intf, callback, packetsPerTransfer, numTransfers):
        def callback_wrapper(buf, ll, prog, user):
            if ll:
                b = ctypes.string_at(buf, ll)
            else:
                b = b''
            return callback(b, prog)

        cb = p_cb_StreamCallback(callback_wrapper)

        # HACK
        keeper.append(cb)

        return FTDIDevice_ReadStream(self._dev, intf, cb, 
                None, packetsPerTransfer, numTransfers)
        



_HW_Init = libov.HW_Init
_HW_Init.argtypes = [pFTDI_Device, ctypes.c_char_p]

def HW_Init(dev, bitstream):
    return _HW_Init(dev._dev, bitstream)


class ProtocolError(Exception):
    pass

class TimeoutError(Exception):
    pass

class _mapped_reg:
    def __init__(self, readfn, writefn, name, addr):
        self.readfn = readfn
        self.writefn = writefn
        self.addr = addr
        self.shadow = 0

    def rd(self):
        self.shadow = self.readfn(self.addr)
        return self.shadow

    def wr(self, value):
        self.shadow = self.writefn(self.addr, value)

class _mapped_regs:
    def __init__(self, d):
        self._d = d

    def __getattr__(self, attr):
        try:
            return self.__dict__['_d'][attr.upper()]
        except KeyError:
            pass

        raise KeyError("No such register %s - did you specify a mapfile?" % attr)


UCFG_REG_GO = 0x80
UCFG_REG_ADDRMASK = 0x3F

SMSC_334x_MAGIC = 0x4240009
SMSC_334x_MAP = {
    "VIDL": 0x00,
    "VIDH": 0x01,
    "PIDL": 0x02,
    "PIDH": 0x03,

    "FUNC_CTL": 0x04,
    "FUNC_CTL_SET": 0x05,
    "FUNC_CTL_CLR": 0x06,

    "INTF_CTL": 0x07,
    "INTF_CTL_SET": 0x08,
    "INTF_CTL_CLR": 0x09,

    "OTG_CTL": 0x0A,
    "OTG_CTL_SET": 0x0B,
    "OTG_CTL_CLR": 0x0C,

    "USB_INT_EN_RISE": 0x0D,
    "USB_INT_EN_RISE_SET": 0x0e,
    "USB_INT_EN_RISE_CLR": 0x0f,

    "USB_INT_EN_FALL": 0x10,
    "USB_INT_EN_FALL_SET": 0x11,
    "USB_INT_EN_FALL_CLR": 0x12,

    "USB_INT_STAT": 0x13,
    "USB_INT_LATCH": 0x14,

    "DEBUG": 0x15,

    "SCRATCH": 0x16,
    "SCRATCH_SET": 0x17,
    "SCRATCH_CLR": 0x18,

    "CARKIT": 0x19,
    "CARKIT_SET": 0x1A,
    "CARKIT_CLR": 0x1B,

    "CARKIT_INT_EN": 0x1D,
    "CARKIT_INT_EN_SET": 0x1E,
    "CARKIT_INT_EN_CLR": 0x1F,

    "CARKIT_INT_STAT": 0x20,
    "CARKIT_INT_LATCH": 0x21,

    "HS_COMP_REG":   0x31,
    "USBIF_CHG_DET": 0x32,
    "HS_AUD_MODE":   0x33,

    "VND_RID_CONV": 0x36,
    "VND_RID_CONV_SET": 0x37,
    "VND_RID_CONV_CLR": 0x38,

    "USBIO_PWR_MGMT": 0x39,
    "USBIO_PWR_MGMT_SET": 0x3A,
    "USBIO_PWR_MGMT_CLR": 0x3B,
}


INCOMPLETE = -1
UNMATCHED = 0
class baseService:
    def presentBytes(self, b):
        if b[0] != self.MAGIC:
            return UNMATCHED

        if len(b) < self.NEEDED_FOR_SIZE:
            return INCOMPLETE

        size = self.getPacketSize(b)

        if len(b) < size:
            return INCOMPLETE

        self.consume(b[:size])

        return size

class IO:
    class __IOService(baseService):
        MAGIC = 0x55
        NEEDED_FOR_SIZE = 1

        def __init__(self):
            self.q = queue.Queue()

        def getPacketSize(self, buf):
            return 5

        def consume(self, buf):
            assert buf[0] == self.MAGIC
            assert len(buf) == 5

            calc_ck = (sum(buf[0:4]) & 0xFF)

            if calc_ck != buf[4]:
                raise ProtocolError(
                    "Checksum for response incorrect: expected %02x, got %02x" %
                    (calc_ck, buf[4])
                )

            self.q.put((buf[1] << 8 | buf[2], buf[3]))

    def __init__(self):
        self.service = IO.__IOService()

    def do_read(self, addr, timeout=None):
        return self.__txn(addr, 0, timeout)

    def do_write(self, addr, value, timeout=None):
        return self.__txn(0x8000 | addr, value, timeout)

    def __txn(self, io_ext, value, timeout):
        msg = [0x55, (io_ext >> 8), io_ext & 0xFF, value]
        checksum = (sum(msg) & 0xFF)
        msg.append(checksum)
        msg = bytes(msg)

        self.service.write(msg)

        try:
            resp = self.service.q.get(True, timeout)
        except queue.Empty:
            raise TimeoutError("IO access timed out")

        r_addr, r_value = resp

        assert r_addr == io_ext

        return r_value

# Basic Test service for testing stream rates and ordering
# Ideally we'd verify the entire LFSR, but python is too slow
# As it is, the rates are CPU-bound
class LFSRTest:
    __stats = collections.namedtuple('LFSR_Stat', 
            ['total', 'error'])

    class __LFSRTestService(baseService):
        MAGIC = 0xAA

        NEEDED_FOR_SIZE = 2

        def __init__(self):
            self.total = 0
            self.reset()

        def reset(self):
            self.state = None
            self.error = 0
            self.total = 0

        def getPacketSize(self, buf):
            # overhead is magic, length
            return buf[1] + 2

        def consume(self, buf):
            assert buf[0] == self.MAGIC
            assert buf[1] + 2 == len(buf)

            self.total += buf[1]

            if self.state != None:
                if buf[2] & 0xFE != (self.state << 1) & 0xFE:
                    self.error = 1

            self.state = buf[-1]

    def __init__(self):
        self.service = LFSRTest.__LFSRTestService()

        self.reset = self.service.reset

    def stats(self):
        return LFSRTest.__stats(total=self.service.total, error=self.service.error)

class OVDevice:
    def __init__(self, mapfile=None, verbose=False):
        self.__is_open = False

        self.dev = FTDIDevice()
        self.verbose = verbose

        self.__addrmap = {}

        if mapfile:
            self.__parse_mapfile(mapfile)


        self.regs = self.__build_map(self.__addrmap, self.ioread, self.iowrite)
        self.ulpiregs = self.__build_map(SMSC_334x_MAP, self.ulpiread, self.ulpiwrite)


        self.clkup = False


        self.io = IO()
        self.lfsrtest = LFSRTest()

        self.__services = [self.io.service, self.lfsrtest.service]

        # Inject a write function to the services
        for service in self.__services:
            def write(msg):
                if self.verbose:
                    print("< %s" % " ".join("%02x" % i for i in msg))

                self.dev.write(FTDI_INTERFACE_A, msg, async=False)

            service.write = write
    
        self.commthread = threading.Thread(target=self.__comms, daemon=True)
        self.__comm_term = False
        self.__comm_exc = None
    
    def __comms(self):
        self.__buf = b""

        def callback(b, prog):
            try:
                if self.verbose and b:
                    print("> %s" % " ".join("%02x" % i for i in b))

                self.__buf += b

                incomplete = False

                while self.__buf and not incomplete:
                    for service in self.__services:
                        code = service.presentBytes(self.__buf)
                        if code == INCOMPLETE:
                            incomplete = True
                            break
                        elif code:
                            self.__buf = self.__buf[code:]
                            break
                    else:
                        print("Unmatched byte %02x - discarding" % self.__buf[0])
                        self.__buf = self.__buf[1:]

                return int(self.__comm_term) 
            except Exception as e:
                self.__comm_term = True
                self.__comm_exc = e
                return 1

        while not self.__comm_term:
            self.dev.read_async(FTDI_INTERFACE_A, callback, 8, 16)

        if self.__comm_exc:
            raise self.__comm_exc
            
    def __build_map(self, addrmap, readfn, writefn):
        d = {}
        for name, addr in addrmap.items():
            d[name] = _mapped_reg(readfn, writefn, name, addr)

        return _mapped_regs(d)


    def __check_clkup(self):
        if self.clkup:
            return True

        self.clkup = self.regs.ucfg_stat.rd() & 0x1

        return self.clkup


    def __parse_mapfile(self, mapfile):

        for line in mapfile.readlines():
            line = line.strip().decode('utf-8')

            line = re.sub('#.*', '', line)
            if not line:
                continue

            m = re.match('\s*(\w+)\s*=\s*(\w+)\s*', line)
            if not m:
                raise ValueError("Mapfile - could not parse %s" % line)

            name = m.group(1)
            value = int(m.group(2), 16)

            self.__addrmap[name] = value


    def resolve_addr(self, sym):
        if type(sym) == int:
            return sym

        try:
            return int(sym, 16)
        except ValueError:
            pass

        try:
            return self.__addrmap[sym.upper()]
        except KeyError:
            raise ValueError("No map for %s" % sym)

    def __del__(self):
        if self.__is_open:
            self.close()

    def open(self, bitstream=None):
        if self.__is_open:
            raise ValueError("OVDevice doubly opened")

        stat = self.dev.open()
        if stat:
            return stat

        if not isinstance(bitstream, bytes) and hasattr(bitstream, 'read'):

            # FIXME: Current bit_file code is heavily dependent on fstream ops
            #  and isn't nice to call with a python file-like object
            #
            # Workaround this by emitting a tempfile
            import tempfile
            import os

            bitfile = tempfile.NamedTemporaryFile(delete=False)

            try:
                bitfile.write(bitstream.read())
                bitfile.close()

                HW_Init(self.dev, bitfile.name.encode('ascii'))
           
            finally:
                # Make sure we cleanup the tempfile
                os.unlink(bitfile.name)

        elif isinstance(bitstream, bytes) or bitstream == None:
            HW_Init(self.dev, bitstream)

        else:
            raise TypeError("bitstream must be bytes or file-like")
        
        self.commthread.start()

        self.__comm_term = False
        self.__is_open = True

    def close(self):
        if not self.__is_open:
            raise ValueError("OVDevice doubly closed")

        self.__comm_term = True
        self.commthread.join()

        self.__is_open = False


    def ulpiread(self, addr):
        assert self.__check_clkup()

        self.regs.ucfg_rcmd.wr(UCFG_REG_GO | (addr & UCFG_REG_ADDRMASK))

        while self.regs.ucfg_rcmd.rd() & UCFG_REG_GO:
            pass

        return self.regs.ucfg_rdata.rd()


    def ulpiwrite(self, addr, value):
        assert self.__check_clkup()

        self.regs.ucfg_wdata.wr(value)
        self.regs.ucfg_wcmd.wr(UCFG_REG_GO | (addr & UCFG_REG_ADDRMASK))
        
        while self.regs.ucfg_wcmd.rd() & UCFG_REG_GO:
            pass

    def ioread(self, addr):
        return self.io.do_read(self.resolve_addr(addr))

    def iowrite(self, addr, value):
        return self.io.do_write(self.resolve_addr(addr), value)





