/* node tests/test_k50_build.js -- executes the SAME packaging core as cscript. */
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');
const build = require('../tools/k50_build.js');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'k50-build-test-'));
const io = {
    exists: p => fs.existsSync(p), mkdir: p => fs.mkdirSync(p, {recursive: true}),
    list: p => fs.readdirSync(p), readText: p => fs.readFileSync(p, 'ascii'),
    writeText: (p, t) => fs.writeFileSync(p, t, {encoding: 'ascii', flag: 'wx'}),
    readBytes: p => Array.from(fs.readFileSync(p)), size: p => fs.statSync(p).size,
    copy: (a, b) => fs.copyFileSync(a, b)
};
let count = 0;
function test(name, fn) { fn(); count++; console.log('PASS ' + name); }
const raw = [255, 255, 98, 123, 60, 0, 1];
const packed = [255, 255, 98, 123, 60, 0, 1, 1];
const report = 'Project compilation was successful\r\nDevice: EP1K50QC208-3\r\n';
const ttf = '255,255,98,123,60,0,1,\r\n';
function fixture(work, variant = 'GAME_K50') {
    const chip = variant === 'GAME_K30' ? 'K30' : 'K50';
    const stream = chip === 'K30' ? raw.map((v, i) => i === 4 ? 57 : v) : raw;
    const encoded = chip === 'K30' ? packed.map((v, i) => i === 4 ? 57 : v) : packed;
    fs.writeFileSync(work + '/SP2_ACEX.rpt', report.replace('K50', chip));
    fs.writeFileSync(work + '/SP2_ACEX.sof', 'synthetic test data');
    fs.writeFileSync(work + '/SP2_ACEX.ttf', stream.join(',') + ',\r\n');
    for (const [name, data] of [[chip === 'K30' ? 'STREAM30.BIN' : 'STREAM50.BIN',stream], ['roundtrip.bin',stream], [chip + '.packed',encoded]]) {
        fs.writeFileSync(work + '/' + name, Buffer.from(data));
    }
}
try {
    for (const variant of ['STANDARD_K50', 'GAME_K50', 'GAME_K30']) {
        test('prepare ' + variant + ' preserves pins and floorplan', () => {
            const work = temp + '/' + variant;
            build.prepare(io, root + '/altera/acex', work, variant);
            const source = io.readText(root + '/altera/acex/K50/SP2_ACEX.ACF');
            const staged = io.readText(work + '/SP2_ACEX.ACF');
            const assignments = t => t.split(/\r?\n/).filter(l => !/^\s*--/.test(l) && /(?:_PIN\s*=\s*\d+|LOCATION\s*=)/.test(l));
            assert.deepStrictEqual(assignments(staged), assignments(source));
            const chip = variant === 'GAME_K30' ? 'K30' : 'K50';
            assert.ok(staged.includes('DEVICE_FOR_TIMING_SYNTHESIS = EP1' + chip + 'QC208-3;'));
            for (const f of io.list(work).filter(n => /\.ACF$/i.test(n))) {
                const devices = io.readText(work+'/'+f).match(/^\s*DEVICE(?:_FOR_TIMING_SYNTHESIS)?\s*=\s*EP1K[^;]+;/gim) || [];
                assert.ok(devices.every(line => line.includes('EP1' + chip + 'QC208-3;')));
            }
            assert.ok(!io.exists(work + '/SP2_ACEX.ttf'));
            const video = io.readText(root + '/altera/acex/' + (variant === 'STANDARD_K50' ? 'K50' : 'GAME_K50') + '/VIDEO2.TDF');
            assert.strictEqual(io.readText(work + '/VIDEO2.TDF'), variant === 'STANDARD_K50' ? video : build.transformGameVideo(video, variant));
            assert.throws(() => build.prepare(io, root + '/altera/acex', work, variant), /already exists/);
        });
    }
    test('target scroll and border stages preserve bus slots and write pipeline', () => {
        const common = io.readText(root + '/altera/acex/GAME_K50/VIDEO2.TDF');
        assert.strictEqual(build.transformGameVideo(common, 'GAME_K30'), common);
        const k50 = build.transformGameVideo(common, 'GAME_K50');
        assert.ok(k50.includes('G_EFFECTIVE[7..0] : DFFE;'));
        assert.ok(!k50.includes('G_EFFECTIVE_X'));
        assert.ok(k50.includes('G_RASTER_BLOCK.ena = G_MODE_CAPTURE;'));
        assert.ok(k50.includes('G_RASTER_BLOCK = (CT[5..3] != 6) or (VDM3[7..5] == 7);'));
        assert.ok(k50.includes('G_APPLY = G_PENDING_VALID & ((G_LOCAL_X[] == 7) or !G_RASTER_BLOCK);'));
        for (const boundary of ['G_RASTER_END : DFFE;', 'G_RASTER_END = (CT[5..3] == 6);', 'or (G_RASTER_END & (MODE0[7..5] != 7)))']) {
            assert.throws(() => build.transformGameVideo(common.replace(boundary, ''), 'GAME_K50'), /review K50/);
        }
        for (let mode = 1; mode <= 3; mode++) {
            assert.ok(common.includes(`MODE${mode}[].ena = G_CAPTURE;`));
            assert.ok(k50.includes(`MODE${mode}[].ena = G_MODE_CAPTURE;`));
            assert.throws(() => build.transformGameVideo(common.replace(`MODE${mode}[].ena = G_CAPTURE;`, ''), 'GAME_K50'), /review K50/);
        }
        const withoutScrollStage = t => t.replace(/G_EFFECTIVE\[7\.\.0\][\s\S]*?(?=G_LOCAL_X)/, '')
            .replace(/G_EFFECTIVE(?:_X)?\[\]\.clk[\s\S]*?(?=G_SCROLL\[\]\.clk)/, '')
            .replace(/MODE([123])\[\]\.ena = G_MODE_CAPTURE;/g, 'MODE$1[].ena = G_CAPTURE;')
            .replace(/G_RASTER_(?:BLOCK|END) : DFFE;/, '')
            .replace(/G_RASTER_(?:BLOCK|END)\.clk[\s\S]*?(?=\r?\n\r?\n)/, '')
            .replace(/G_APPLY = G_PENDING_VALID[\s\S]*?;/, '');
        assert.strictEqual(withoutScrollStage(k50), withoutScrollStage(common));
        assert.throws(() => build.transformGameVideo(common.replace('G_EFFECTIVE_X[3..0] : DFFE;', ''), 'GAME_K50'), /review K50/);
        assert.throws(() => build.transformGameVideo(common, 'STANDARD_K50'), /Standard/);
    });
    test('valid packaging and variant gating', () => {
        const work = temp + '/GAME_K50'; fixture(work);
        assert.throws(() => build.verifyDirectory(io, work, 'STANDARD_K50'), /Variant mismatch/);
        build.verifyDirectory(io, work, 'GAME_K50');
        assert.deepStrictEqual(io.readBytes(work + '/K50.ACX'), packed);
        assert.throws(() => build.verifyDirectory(io, work, 'GAME_K50'), /already exists/);
    });
    test('K30 packaging rejects K50 report and bitstream', () => {
        const work = temp + '/GAME_K30'; fixture(work, 'GAME_K30');
        fs.writeFileSync(work + '/SP2_ACEX.rpt', report);
        assert.throws(() => build.verifyDirectory(io, work, 'GAME_K30'), /Device/);
        assert.ok(!io.exists(work + '/K30.ACX'));
        fs.writeFileSync(work + '/SP2_ACEX.rpt', report.replace('K50', 'K30'));
        fs.writeFileSync(work + '/STREAM30.BIN', Buffer.from(raw));
        assert.throws(() => build.verifyDirectory(io, work, 'GAME_K30'), /header/);
        assert.ok(!io.exists(work + '/K30.ACX'));
        fixture(work, 'GAME_K30');
        build.verifyDirectory(io, work, 'GAME_K30');
        assert.deepStrictEqual(io.readBytes(work + '/K30.ACX'), packed.map((v, i) => i === 4 ? 57 : v));
        assert.ok(!io.exists(work + '/K50.ACX'));
        assert.throws(() => build.verifyDirectory(io, work, 'GAME_K30'), /already exists/);
    });
    test('legacy BIOS stream publishes only validated standard raw data', () => {
        const work = temp + '/STANDARD_K50', target = temp + '/STREAM.BIN';
        fixture(work);
        fs.writeFileSync(target, 'previous BIOS stream');
        assert.throws(() => build.publishStandardStream(io, work, target));
        assert.strictEqual(io.readText(target), 'previous BIOS stream');
        build.verifyDirectory(io, work, 'STANDARD_K50');
        build.publishStandardStream(io, work, target);
        assert.deepStrictEqual(io.readBytes(target), raw);
        assert.throws(() => build.publishStandardStream(io, temp + '/GAME_K50', target), /Only STANDARD/);
        assert.throws(() => build.publishStandardStream(io, temp + '/GAME_K30', target), /Only STANDARD/);
        fs.writeFileSync(work + '/STREAM50.BIN', Buffer.from([1,2,3]));
        assert.throws(() => build.publishStandardStream(io, work, target));
        assert.deepStrictEqual(io.readBytes(target), raw);
    });
    const cases = [
        ['wrong chip', report.replace('EP1K50', 'EP1K30'), 1, ttf, raw, packed, raw],
        ['two chips', report + 'Device: EP1K50QC208-3\n', 1, ttf, raw, packed, raw],
        ['failed fitting', 'Error: fitting failed', 1, ttf, raw, packed, raw],
        ['error with success banner', report + 'Error: invalid node\n', 1, ttf, raw, packed, raw],
        ['empty SOF', report, 0, ttf, raw, packed, raw],
        ['empty ACX', report, 1, ttf, raw, [], raw],
        ['wrong header', report, 1, ttf, [255,255,98,123,57,0,1], packed, raw],
        ['roundtrip corruption', report, 1, ttf, raw, packed, [1]],
        ['TTF corruption', report, 1, '255,255,98,123,60,0,2,', raw, packed, raw],
        ['truncated zero pair', report, 1, ttf, raw, packed.slice(0,6), raw],
        ['zero length run', report, 1, ttf, raw, [255,255,98,123,60,0,0,1], raw],
        ['64 KiB + 1 rejected', report, 1, ttf, raw, new Array(65537).fill(1), raw]
    ];
    for (const [name, ...args] of cases) test(name, () => assert.throws(() => build.verify(...args)));
    test('exact 64 KiB accepted', () => {
        const bigRaw = raw.concat(new Array(65528).fill(1));
        const bigPacked = packed.concat(new Array(65528).fill(1));
        assert.strictEqual(bigPacked.length, 65536);
        build.verify(report, 1, bigRaw.join(','), bigRaw, bigPacked, bigRaw);
    });
    test('first zero run can extend beyond header', () => {
        const stream = raw.slice(0,6).concat([0,1]);
        const encoded = packed.slice(0,6).concat([2,1]);
        build.verify(report,1,stream.join(','),stream,encoded,stream);
    });
    test('TTF line boundaries and invalid tokens', () => {
        assert.deepStrictEqual(build.parseTtf('255, 255,\r\n98,123\n60,0,1,\n'), raw);
        for (const bad of ['1,,2', '1,256', '1,-1', '1,1.5', '1,x']) assert.throws(() => build.parseTtf(bad));
    });
    test('missing compiler result never publishes ACX', () => {
        const work = temp + '/missing'; build.prepare(io, root + '/altera/acex', work, 'GAME_K50');
        fixture(work); fs.unlinkSync(work + '/SP2_ACEX.sof');
        assert.throws(() => build.verifyDirectory(io, work, 'GAME_K50'));
        assert.ok(!io.exists(work + '/K50.ACX'));
    });
    test('commented floorplan excluded from audit', () => {
        const out = build.transformAcf('\t-- |x : LOCATION = LC1_A1;\n\t|y : LOCATION = EAB_A;', 'GAME_K50', 'x.acf');
        assert.strictEqual(out.audit.length, 1);
    });
    console.log(count + ' build tests passed; Windows COM/cmd runtime still requires a Windows run.');
} finally { fs.rmSync(temp, {recursive: true, force: true}); }
