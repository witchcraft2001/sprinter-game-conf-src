/* Windows Script Host JScript (ES3), also testable with Node.js.
 * No PowerShell, Python or third-party modules in the Windows build.
 */
var K50Build = (function () {
    function requireCondition(ok, message) { if (!ok) { throw new Error(message); } }
    function target(variant) {
        requireCondition(variant === 'GAME_K30' || variant === 'GAME_K50' || variant === 'STANDARD_K50', 'Invalid variant');
        var chip = variant === 'GAME_K30' ? 'K30' : 'K50';
        return {chip: chip, device: 'EP1' + chip + 'QC208-3', header: chip === 'K30' ? 57 : 60,
                stream: chip === 'K30' ? 'STREAM30.BIN' : 'STREAM50.BIN'};
    }
    function transformAcf(text, variant, name) {
        var device = target(variant).device;
        var lines = text.split(/\r?\n/), audit = [], i, line;
        for (i = 0; i < lines.length; i++) {
            line = lines[i];
            if (/^\s*--/.test(line)) { continue; }
            if (/^\s*DEVICE_FOR_TIMING_SYNTHESIS\s*=/.test(line)) {
                lines[i] = '    DEVICE_FOR_TIMING_SYNTHESIS = ' + device + ';';
            } else if (/^\s*DEVICE\s*=\s*EP1K/.test(line)) {
                lines[i] = '    DEVICE = ' + device + ';';
            }
            if (/LOCATION\s*=\s*(LC\d+_|EAB_)/.test(line)) {
                // Preserve the baseline and write-critical placement. The fitter
                // must flag invalid target locations; record all inherited constraints.
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
    function transformGameVideo(text, variant) {
        target(variant);
        requireCondition(variant !== 'STANDARD_K50', 'Standard video must not be transformed');
        if (variant === 'GAME_K30') { return text; }
        // K30 keeps four scroll-prefetch registers; K50 benefits from eight.
        // Exact, checked substitutions keep a single common video source and
        // preserve all bus phases, CPU strobes and physical timing chains.
        var declarations = /G_EFFECTIVE\[7\.\.0\] : NODE;\s*G_EFFECTIVE_X\[3\.\.0\] : DFFE;\s*G_EFFECTIVE_Y\[3\.\.0\] : NODE;/g;
        var stage = /G_EFFECTIVE_X\[\]\.clk = CLK42; G_EFFECTIVE_X\[\]\.ena = \(VCM\[\] == 0\);\s*IF G_APPLY THEN\s*G_EFFECTIVE_X\[\] = G_PENDING\[3\.\.0\]; G_EFFECTIVE_Y\[\] = G_PENDING\[7\.\.4\];\s*ELSE\s*G_EFFECTIVE_X\[\] = G_SCROLL\[3\.\.0\]; G_EFFECTIVE_Y\[\] = G_SCROLL\[7\.\.4\];\s*END IF;\s*G_EFFECTIVE\[\] = \(G_EFFECTIVE_Y\[\],G_EFFECTIVE_X\[\]\);/g;
        requireCondition((text.match(declarations) || []).length === 1 && (text.match(stage) || []).length === 1,
                         'Game scroll pipeline changed; review K50 staging transform');
        // The same physical/source boundary rule fits K30 with a CT=2 tag.
        // K50 times better with graphics classification folded into a CT=5
        // blocking tag. Holding it with MODE0 preserves backtrack behavior.
        var boundaryDecl = 'G_RASTER_END : DFFE;';
        var boundaryStage = /G_RASTER_END\.clk = CLK42; G_RASTER_END\.ena = \(VCM\[\] == 4\);\s*G_RASTER_END = \(CT\[5\.\.3\] == 6\);/g;
        var boundaryApply = /G_APPLY = G_PENDING_VALID & \(\(G_LOCAL_X\[\] == 7\)\s*or \(G_RASTER_END & \(MODE0\[7\.\.5\] != 7\)\)\);/g;
        requireCondition(text.split(boundaryDecl).length === 2 &&
                         (text.match(boundaryStage) || []).length === 1 &&
                         (text.match(boundaryApply) || []).length === 1,
                         'Game physical boundary changed; review K50 staging transform');
        text = text.replace(boundaryDecl, 'G_RASTER_BLOCK : DFFE;')
                   .replace(boundaryStage, 'G_RASTER_BLOCK.clk = CLK42; G_RASTER_BLOCK.ena = G_MODE_CAPTURE;\r\n' +
                                           '\tG_RASTER_BLOCK = (CT[5..3] != 6) or (VDM3[7..5] == 7);')
                   .replace(boundaryApply, 'G_APPLY = G_PENDING_VALID & ((G_LOCAL_X[] == 7) or !G_RASTER_BLOCK);');
        // K30 only holds MODE0 while clipping a backwards border reload.
        // K50 routes/times better when all descriptor registers share that
        // enable. Pixel addresses during border may differ; displayed RGB,
        // blank/IRQ and control acceptance are identical.
        for (var mode = 1; mode <= 3; mode++) {
            var enable = 'MODE' + mode + '[].ena = G_CAPTURE;';
            requireCondition(text.split(enable).length === 2,
                             'Game border pipeline changed; review K50 staging transform');
            text = text.replace(enable, 'MODE' + mode + '[].ena = G_MODE_CAPTURE;');
        }
        return text.replace(declarations, 'G_EFFECTIVE[7..0] : DFFE;')
                   .replace(stage, 'G_EFFECTIVE[].clk = CLK42; G_EFFECTIVE[].ena = (VCM[] == 0);\r\n' +
                                   '\tIF G_APPLY THEN G_EFFECTIVE[] = G_PENDING[];\r\n' +
                                   '\tELSE G_EFFECTIVE[] = G_SCROLL[]; END IF;');
    }
    function compare(a, b, name) {
        requireCondition(a.length === b.length, name + ' length mismatch');
        for (var i = 0; i < a.length; i++) {
            requireCondition(a[i] === b[i], name + ' mismatch at byte ' + i);
        }
    }
    function verify(report, sofSize, ttf, raw, packed, back, variant) {
        var config = target(typeof variant === 'undefined' ? 'GAME_K50' : variant);
        requireCondition(/Project compilation was successful/i.test(report), 'No successful compilation in report');
        requireCondition(!/^\s*(?:Error|Fatal error):/im.test(report), 'Compiler errors in report');
        var devices = report.match(/^\s*Device:[^\r\n]*/gim) || [];
        requireCondition(devices.length === 1 && new RegExp('^\\s*Device:\\s*' + config.device + '\\s*$', 'i').test(devices[0]),
                         'Report must contain exactly one Device: ' + config.device);
        requireCondition(sofSize > 0 && raw.length > 0 && back.length > 0 && packed.length > 0,
                         'Missing or empty compiler/converter result');
        requireCondition(packed.length <= 65536, 'ACX exceeds four 16 KiB loader pages');
        var header = [255, 255, 98, 123, config.header, 0], i, j = 0, n, value;
        for (i = 0; i < header.length; i++) {
            requireCondition(raw[i] === header[i], 'Bitstream header is not ACEX ' + config.chip);
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
        target(variant);
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
            } else if (variant !== 'STANDARD_K50' && /^VIDEO2\.TDF$/i.test(name)) {
                io.writeText(work + '/' + name, transformGameVideo(io.readText(source + '/GAME_K50/VIDEO2.TDF'), variant));
            } else { io.copy(source + '/K50/' + name, work + '/' + name); }
            copied.push(name);
        }
        io.writeText(work + '/floorplan-audit.txt', audit.join('\r\n') + '\r\n');
        io.writeText(work + '/variant.txt', variant + '\r\n');
        io.writeText(work + '/source-files.txt', copied.sort().join('\r\n') + '\r\n');
    }
    function verifyDirectory(io, work, variant) {
        var config = target(variant), packedName = config.chip + '.packed', acxName = config.chip + '.ACX';
        requireCondition(io.readText(work + '/variant.txt').replace(/\s/g, '') === variant, 'Variant mismatch');
        requireCondition(!io.exists(work + '/' + acxName), 'Release ACX already exists; refusing re-verification');
        verify(io.readText(work + '/SP2_ACEX.rpt'), io.size(work + '/SP2_ACEX.sof'),
               io.readText(work + '/SP2_ACEX.ttf'), io.readBytes(work + '/' + config.stream),
               io.readBytes(work + '/' + packedName), io.readBytes(work + '/roundtrip.bin'), variant);
        io.copy(work + '/' + packedName, work + '/' + acxName);
        io.writeText(work + '/package-verification.txt', 'VERIFIED PACKAGING ONLY: ' + variant + '\r\n');
    }
    function publishStandardStream(io, work, target) {
        requireCondition(io.readText(work + '/variant.txt').replace(/\s/g, '') === 'STANDARD_K50',
                         'Only STANDARD_K50 may publish the BIOS STREAM.BIN');
        // Revalidate the actual inputs; a marker file alone is not sufficient.
        var raw = io.readBytes(work + '/STREAM50.BIN');
        verify(io.readText(work + '/SP2_ACEX.rpt'), io.size(work + '/SP2_ACEX.sof'),
               io.readText(work + '/SP2_ACEX.ttf'), raw,
               io.readBytes(work + '/K50.ACX'), io.readBytes(work + '/roundtrip.bin'));
        io.copy(work + '/STREAM50.BIN', target);
        compare(io.readBytes(target), raw, 'Published BIOS stream');
    }
    return {transformAcf: transformAcf, transformGameVideo: transformGameVideo, parseTtf: parseTtf, verify: verify,
            prepare: prepare, verifyDirectory: verifyDirectory,
            publishStandardStream: publishStandardStream};
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
        if (WScript.Arguments.length !== 3) { throw new Error('Usage: k50_build.js Prepare|Verify|PublishStandard work GAME_K30|GAME_K50|STANDARD_K50'); }
        var stage = WScript.Arguments(0), work = path(WScript.Arguments(1)), variant = WScript.Arguments(2);
        var source = fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)), 'altera\\acex');
        if (stage === 'Prepare') { K50Build.prepare(io, source, work, variant); }
        else if (stage === 'Verify') { K50Build.verifyDirectory(io, work, variant); }
        else if (stage === 'PublishStandard' && variant === 'STANDARD_K50') {
            K50Build.publishStandardStream(io, work, fso.BuildPath(source, 'STREAM.BIN'));
        }
        else { throw new Error('Invalid stage'); }
        WScript.Quit(0);
    } catch (error) {
        WScript.Echo('ACEX build failed: ' + error.message);
        WScript.Quit(1);
    }
}
