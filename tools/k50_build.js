/* Windows Script Host JScript (ES3), also testable with Node.js.
 * No PowerShell, Python or third-party modules in the Windows build.
 */
var K50Build = (function () {
    function requireCondition(ok, message) { if (!ok) { throw new Error(message); } }
    function transformAcf(text, variant, name) {
        var lines = text.split(/\r?\n/), audit = [], i, line;
        for (i = 0; i < lines.length; i++) {
            line = lines[i];
            if (/^\s*--/.test(line)) { continue; }
            if (/^\s*DEVICE_FOR_TIMING_SYNTHESIS\s*=/.test(line)) {
                lines[i] = '    DEVICE_FOR_TIMING_SYNTHESIS = EP1K50QC208-3;';
            } else if (/^\s*DEVICE\s*=\s*EP1K/.test(line)) {
                lines[i] = '    DEVICE = EP1K50QC208-3;';
            }
            if (/LOCATION\s*=\s*(LC\d+_|EAB_)/.test(line)) {
                // Preserve the baseline and write-critical placement. The fitter
                // must flag invalid K50 locations; record all inherited constraints.
                audit.push(name + ': PRESERVED, requires fitting review: ' + line);
            }
        }
        return {text: lines.join('\r\n'), audit: audit};
    }
    function parseTtf(ttf) {
        var result = [], lines = ttf.split(/\r?\n/), i, j, tokens, line, token;
        for (i = 0; i < lines.length; i++) {
            line = lines[i].replace(/^\s+|\s+$/g, '');
            if (line === '') { continue; }
            tokens = line.replace(/,\s*$/, '').split(',');
            for (j = 0; j < tokens.length; j++) {
                token = tokens[j].replace(/^\s+|\s+$/g, '');
                requireCondition(/^\d{1,3}$/.test(token) && Number(token) <= 255,
                                 'Invalid TTF byte at line ' + (i + 1));
                result.push(Number(token));
            }
        }
        return result;
    }
    function compare(a, b, name) {
        requireCondition(a.length === b.length, name + ' length mismatch');
        for (var i = 0; i < a.length; i++) {
            requireCondition(a[i] === b[i], name + ' mismatch at byte ' + i);
        }
    }
    function verify(report, sofSize, ttf, raw, packed, back) {
        requireCondition(/Project compilation was successful/i.test(report), 'No successful compilation in report');
        requireCondition(!/^\s*(?:Error|Fatal error):/im.test(report), 'Compiler errors in report');
        var devices = report.match(/^\s*Device:[^\r\n]*/gim) || [];
        requireCondition(devices.length === 1 && /^\s*Device:\s*EP1K50QC208-3\s*$/i.test(devices[0]),
                         'Report must contain exactly one Device: EP1K50QC208-3');
        requireCondition(sofSize > 0 && raw.length > 0 && back.length > 0 && packed.length > 0,
                         'Missing or empty compiler/converter result');
        requireCondition(packed.length <= 65536, 'ACX exceeds four 16 KiB loader pages');
        var header = [255, 255, 98, 123, 60, 0], i, j = 0, n, value;
        for (i = 0; i < header.length; i++) {
            requireCondition(raw[i] === header[i], 'Bitstream header is not ACEX K50');
        }
        compare(parseTtf(ttf), raw, 'TTF/stream');
        compare(back, raw, 'Roundtrip');
        // Independent strict depacker: do not trust the legacy utility's exit code.
        for (i = 0; i < packed.length; i++) {
            value = packed[i]; n = 1;
            if (value === 0) {
                i++;
                requireCondition(i < packed.length && packed[i] > 0, 'Invalid zero run');
                n = packed[i];
            }
            while (n-- > 0) {
                requireCondition(j < raw.length && raw[j] === value, 'Packed data mismatch at byte ' + j);
                j++;
            }
        }
        requireCondition(j === raw.length, 'Packed stream truncated');
    }
    function prepare(io, source, work, variant) {
        requireCondition(variant === 'GAME_K50' || variant === 'STANDARD_K50', 'Invalid variant');
        requireCondition(!io.exists(work), 'Work directory already exists; refusing stale inputs');
        io.mkdir(work);
        var files = io.list(source + '/K50'), audit = [], copied = [], i, name, result;
        for (i = 0; i < files.length; i++) {
            name = files[i];
            if (!/\.(TDF|INC|MIF|ACF)$/i.test(name)) { continue; }
            if (/\.ACF$/i.test(name)) {
                result = transformAcf(io.readText(source + '/K50/' + name), variant, name);
                io.writeText(work + '/' + name, result.text);
                audit = audit.concat(result.audit);
            } else { io.copy(source + '/K50/' + name, work + '/' + name); }
            copied.push(name);
        }
        if (variant === 'GAME_K50') { io.copy(source + '/GAME_K50/VIDEO2.TDF', work + '/VIDEO2.TDF'); }
        io.writeText(work + '/floorplan-audit.txt', audit.join('\r\n') + '\r\n');
        io.writeText(work + '/variant.txt', variant + '\r\n');
        io.writeText(work + '/source-files.txt', copied.sort().join('\r\n') + '\r\n');
    }
    function verifyDirectory(io, work, variant) {
        requireCondition(io.readText(work + '/variant.txt').replace(/\s/g, '') === variant, 'Variant mismatch');
        requireCondition(!io.exists(work + '/K50.ACX'), 'Release ACX already exists; refusing re-verification');
        verify(io.readText(work + '/SP2_ACEX.rpt'), io.size(work + '/SP2_ACEX.sof'),
               io.readText(work + '/SP2_ACEX.ttf'), io.readBytes(work + '/STREAM50.BIN'),
               io.readBytes(work + '/K50.packed'), io.readBytes(work + '/roundtrip.bin'));
        io.copy(work + '/K50.packed', work + '/K50.ACX');
        io.writeText(work + '/package-verification.txt', 'VERIFIED PACKAGING ONLY: ' + variant + '\r\n');
    }
    return {transformAcf: transformAcf, parseTtf: parseTtf, verify: verify,
            prepare: prepare, verifyDirectory: verifyDirectory};
}());

if (typeof module !== 'undefined') { module.exports = K50Build; }
if (typeof WScript !== 'undefined') {
    try {
        var fso = new ActiveXObject('Scripting.FileSystemObject');
        function path(p) { return fso.GetAbsolutePathName(p.replace(/\//g, '\\')); }
        var io = {
            exists: function (p) { return fso.FileExists(path(p)) || fso.FolderExists(path(p)); },
            mkdir: function (p) {
                var parent = fso.GetParentFolderName(path(p));
                if (!fso.FolderExists(parent)) { io.mkdir(parent); }
                fso.CreateFolder(path(p));
            },
            list: function (p) {
                var e = new Enumerator(fso.GetFolder(path(p)).Files), result = [];
                for (; !e.atEnd(); e.moveNext()) { result.push(e.item().Name); }
                return result;
            },
            readText: function (p) { var f = fso.OpenTextFile(path(p), 1); var t = f.ReadAll(); f.Close(); return t; },
            writeText: function (p, t) { var f = fso.CreateTextFile(path(p), false, false); f.Write(t); f.Close(); },
            readBytes: function (p) {
                var stream = new ActiveXObject('ADODB.Stream'); stream.Type = 1; stream.Open();
                stream.LoadFromFile(path(p));
                var bytes = stream.Size ? new VBArray(stream.Read()).toArray() : [];
                stream.Close(); return bytes;
            },
            size: function (p) { return fso.GetFile(path(p)).Size; },
            copy: function (a, b) { fso.CopyFile(path(a), path(b), true); }
        };
        if (WScript.Arguments.length !== 3) { throw new Error('Usage: k50_build.js Prepare|Verify work GAME_K50|STANDARD_K50'); }
        var stage = WScript.Arguments(0), work = path(WScript.Arguments(1)), variant = WScript.Arguments(2);
        var source = fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)), 'altera\\acex');
        if (stage === 'Prepare') { K50Build.prepare(io, source, work, variant); }
        else if (stage === 'Verify') { K50Build.verifyDirectory(io, work, variant); }
        else { throw new Error('Invalid stage'); }
        WScript.Quit(0);
    } catch (error) {
        WScript.Echo('K50 build failed: ' + error.message);
        WScript.Quit(1);
    }
}
