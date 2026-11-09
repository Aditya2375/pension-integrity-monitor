"""Appeal evidence intake. Files are parsed, not just sniffed: PNG chunk CRCs,
JPEG marker walk, PDF structure with active-content tokens refused. This is a
structural check, not a malware scan. Accepted files stay in a private
quarantine directory (0700 dir, 0600 files, random names) and staff can only
download them as opaque attachments. Treat every file as untrusted.
"""
import os
import re
import struct
import uuid
import zlib

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_SIDE = 12_000


class EvidenceError(ValueError):
    pass


def _dims_ok(w, h):
    if not (1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE and w * h <= MAX_PIXELS):
        raise EvidenceError("The image dimensions are not acceptable.")


def parse_png(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise EvidenceError("not a PNG")
    pos, n, seen_ihdr, seen_idat = 8, 0, False, False
    while pos + 12 <= len(data):
        n += 1
        if n > 5000:
            raise EvidenceError("The PNG has too many parts.")
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        end = pos + 8 + length
        if length > len(data) or end + 4 > len(data):
            raise EvidenceError("The PNG is cut short.")
        body = data[pos + 8:end]
        (crc,) = struct.unpack(">I", data[end:end + 4])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise EvidenceError("The PNG is damaged.")
        if n == 1:
            if ctype != b"IHDR" or length != 13:
                raise EvidenceError("The PNG header is wrong.")
            w, h, depth, color = struct.unpack(">IIBB", body[:10])
            if (depth, color) not in {(d, c) for c, ds in {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}.items() for d in ds}:
                raise EvidenceError("The PNG format is not supported.")
            _dims_ok(w, h)
            seen_ihdr = True
        seen_idat = seen_idat or ctype == b"IDAT"
        pos = end + 4
        if ctype == b"IEND":
            if pos != len(data) or not (seen_ihdr and seen_idat):
                raise EvidenceError("The PNG has extra or missing data.")
            return
    raise EvidenceError("The PNG has no end.")


def parse_jpeg(data):
    if not data.startswith(b"\xff\xd8"):
        raise EvidenceError("not a JPEG")
    pos, got_sof, got_sos = 2, False, False
    while pos < len(data):
        if data[pos] != 0xFF:
            raise EvidenceError("The JPEG is damaged.")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        marker = data[pos] if pos < len(data) else 0
        pos += 1
        if marker == 0xD9:
            if not (got_sof and got_sos) or data[pos:].strip(b"\x00"):
                raise EvidenceError("The JPEG has extra or missing data.")
            return
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(data):
            raise EvidenceError("The JPEG is cut short.")
        (seglen,) = struct.unpack(">H", data[pos:pos + 2])
        if seglen < 2 or pos + seglen > len(data):
            raise EvidenceError("The JPEG is cut short.")
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[pos + 3:pos + 7])
            _dims_ok(w, h)
            got_sof = True
        pos += seglen
        if marker == 0xDA:   # entropy-coded data until the next real marker
            got_sos = True
            while pos + 1 < len(data):
                if data[pos] == 0xFF and data[pos + 1] not in (0x00,) and not (0xD0 <= data[pos + 1] <= 0xD7):
                    break
                pos += 1
    raise EvidenceError("The JPEG has no end.")


_PDF_BAD = re.compile(rb"/(JavaScript|JS|Launch|OpenAction|AA|EmbeddedFile|EmbeddedFiles|RichMedia|XFA|URI|SubmitForm|GoToR|GoToE|ImportData|ObjStm|Encrypt|Movie|Sound)\b", re.I)


def parse_pdf(data):
    """Structural sanity only. Walk the file the way a reader starts: header,
    trailer with /Root, startxref pointing at a real xref table or xref stream
    object, and every object closed. Active content is refused outright."""
    if not re.match(rb"%PDF-(1\.[0-7]|2\.0)\r?\n", data[:12]):
        raise EvidenceError("not a PDF")
    tail = data[-1100:]
    if not tail.rstrip().endswith(b"%%EOF"):
        raise EvidenceError("The PDF is incomplete.")
    m = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", tail)
    if not m:
        raise EvidenceError("The PDF is incomplete.")
    off = int(m.group(1))
    if not (0 < off < len(data)) or not (data[off:off + 4] == b"xref" or re.match(rb"\d+\s+\d+\s+obj\b", data[off:off + 30])):
        raise EvidenceError("The PDF index is damaged.")
    opens, closes = len(re.findall(rb"(?<![A-Za-z0-9])\d+\s+\d+\s+obj\b", data)), len(re.findall(rb"\bendobj\b", data))
    if opens < 1 or opens != closes or not re.search(rb"/Root\s+\d+\s+\d+\s+R", data):
        raise EvidenceError("The PDF is damaged.")
    if re.search(rb"/[A-Za-z]*#[0-9A-Fa-f]{2}", data) or _PDF_BAD.search(data):
        raise EvidenceError("The PDF contains features that are not accepted. Please send a plain scan or photo.")


KINDS = {"png": ("image/png", parse_png), "jpg": ("image/jpeg", parse_jpeg), "pdf": ("application/pdf", parse_pdf)}


def sniff(data):
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"%PDF-"):
        return "pdf"
    raise EvidenceError("Only PDF, JPG or PNG files are accepted.")


def validate(data):
    """Return (ext, mime) or raise EvidenceError."""
    if len(data) > MAX_BYTES:
        raise EvidenceError("The file is larger than 5 MB.")
    ext = sniff(data)
    if len(data) < 16:
        raise EvidenceError("The file is empty or too small.")
    KINDS[ext][1](data)
    return ext, KINDS[ext][0]


def store(directory, data, ext):
    """Write into <directory>/quarantine with owner-only permissions."""
    qdir = os.path.join(directory, "quarantine")
    os.makedirs(qdir, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    os.chmod(qdir, 0o700)
    path = os.path.join(qdir, uuid.uuid4().hex + "." + ext)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def readable_path(directory, path, expected_sha256):
    """Refuse to serve anything that moved out of quarantine or changed."""
    import hashlib
    qdir = os.path.realpath(os.path.join(directory, "quarantine"))
    real = os.path.realpath(path)
    if os.path.commonpath([qdir, real]) != qdir or not os.path.isfile(real):
        raise EvidenceError("evidence file is not where it should be")
    with open(real, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != expected_sha256:
            raise EvidenceError("evidence file changed since upload")
    return real
