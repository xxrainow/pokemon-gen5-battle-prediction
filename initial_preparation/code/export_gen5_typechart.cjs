/** Export the resolved Gen 5 type chart through Pokemon Showdown's official Dex loader. */
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {parseArgs} = require('node:util');
const {Dex} = require('pokemon-showdown');

const ROOT = path.resolve(__dirname, '../..');
// Only the order/names are fixed here; every multiplier comes from the official loader.
const TYPES = [
  'Normal', 'Fire', 'Water', 'Electric', 'Grass', 'Ice', 'Fighting', 'Poison',
  'Ground', 'Flying', 'Psychic', 'Bug', 'Rock', 'Ghost', 'Dragon', 'Dark', 'Steel',
];

function sha256(content) {
  return crypto.createHash('sha256').update(content).digest('hex');
}

function multiplier(dex, attack, defense) {
  // Effectiveness alone returns 0 (the exponent) for immunities: check immunity first.
  return dex.getImmunity(attack, defense) ? 2 ** dex.getEffectiveness(attack, defense) : 0;
}

function main() {
  const {values} = parseArgs({options: {
    'output-dir': {type: 'string'}, help: {type: 'boolean', short: 'h'},
  }});
  if (values.help) {
    console.log('node initial_preparation/code/export_gen5_typechart.cjs [--output-dir DIRECTORY]');
    console.log('기본 출력: data/external/gen5_typechart.csv, gen5_typechart_info.json');
    return;
  }
  const outputDir = path.resolve(values['output-dir'] || path.join(ROOT, 'data/external'));
  const csvPath = path.join(outputDir, 'gen5_typechart.csv');
  const infoPath = path.join(outputDir, 'gen5_typechart_info.json');
  if ([csvPath, infoPath].some(p => fs.existsSync(p))) {
    throw new Error('출력 파일이 이미 있습니다. --output-dir로 다른 폴더를 지정하세요.');
  }

  const packagePath = require.resolve('pokemon-showdown/package.json');
  const packageDir = path.dirname(packagePath);
  const installed = require(packagePath);
  const pinned = require(path.join(ROOT, 'package.json')).dependencies['pokemon-showdown'];
  const locked = require(path.join(ROOT, 'package-lock.json')).packages['node_modules/pokemon-showdown'];
  assert.equal(installed.version, pinned, '설치 버전과 고정 버전 불일치');
  assert.equal(installed.version, locked.version, '설치 버전과 lock 버전 불일치');
  assert.ok(locked.integrity, '패키지 무결성 기록 누락');

  const dex = Dex.mod('gen5');
  assert.equal(dex.gen, 5);
  assert.equal(dex.currentMod, 'gen5');
  assert.deepEqual([...dex.types.names()].sort(), [...TYPES].sort());
  assert.equal(new Set(TYPES).size, 17);
  const matrix = {};
  let singleChecks = 0;
  for (const attack of TYPES) {
    matrix[attack] = {};
    for (const defense of TYPES) {
      const value = multiplier(dex, attack, defense);
      assert.ok([0, 0.5, 1, 2].includes(value));
      // Check the API conversion against the loader's fully resolved damageTaken codes.
      const code = dex.types.get(defense).damageTaken[attack] ?? 0;
      assert.equal(value, {0: 1, 1: 2, 2: 0.5, 3: 0}[code]);
      matrix[attack][defense] = value;
      singleChecks++;
    }
  }

  // All 17 single and 136 distinct dual defenses, for every attacking type.
  let combinationChecks = 0;
  for (const attack of TYPES) {
    for (let i = 0; i < TYPES.length; i++) {
      assert.equal(matrix[attack][TYPES[i]], multiplier(dex, attack, [TYPES[i]]));
      combinationChecks++;
      for (let j = i + 1; j < TYPES.length; j++) {
        assert.equal(matrix[attack][TYPES[i]] * matrix[attack][TYPES[j]],
          multiplier(dex, attack, [TYPES[i], TYPES[j]]));
        combinationChecks++;
      }
    }
  }
  const examples = [
    ['Ghost', ['Steel'], 0.5], ['Dark', ['Steel'], 0.5],
    ['Normal', ['Ghost'], 0], ['Electric', ['Ground'], 0],
    ['Ground', ['Flying'], 0], ['Fire', ['Water'], 0.5],
    ['Water', ['Fire'], 2], ['Normal', ['Fire'], 1],
    ['Rock', ['Fire', 'Flying'], 4], ['Water', ['Water', 'Dragon'], 0.25],
    ['Electric', ['Water', 'Ground'], 0], ['Grass', ['Water', 'Ground'], 4],
  ].map(([attack, defense, expected]) => {
    const actual = defense.reduce((value, type) => value * matrix[attack][type], 1);
    assert.equal(actual, expected);
    assert.equal(actual, multiplier(dex, attack, defense));
    return {attack, defense, expected, actual};
  });
  const generationChecks = ['Ghost', 'Dark'].map(attack => {
    const gen5 = matrix[attack].Steel;
    const gen6 = multiplier(Dex.mod('gen6'), attack, 'Steel');
    assert.equal(gen5, 0.5);
    assert.equal(gen6, 1);
    return {attack, defense: 'Steel', gen5, gen6};
  });

  const inheritance = [];
  const loaderFiles = ['dist/sim/dex.js', 'dist/sim/dex-data.js'];
  let current = dex;
  while (!inheritance.includes(current.currentMod)) {
    inheritance.push(current.currentMod);
    for (const name of ['typechart.js', 'scripts.js']) {
      const absolute = path.join(current.dataDir, name);
      if (fs.existsSync(absolute)) loaderFiles.push(path.relative(packageDir, absolute));
    }
    if (!current.parentMod) break;
    current = Dex.mod(current.parentMod);
  }
  const loaderHashes = Object.fromEntries([...new Set(loaderFiles)].map(name => [
    name.split(path.sep).join('/'), sha256(fs.readFileSync(path.join(packageDir, name))),
  ]));
  const csv = [
    ['attack_type', ...TYPES].join(','),
    ...TYPES.map(attack => [attack, ...TYPES.map(defense => matrix[attack][defense])].join(',')),
  ].join('\n') + '\n';
  const info = {
    generation: 5, mod: 'gen5',
    source: {
      repository: 'https://github.com/smogon/pokemon-showdown',
      documentation: 'https://github.com/smogon/pokemon-showdown/blob/master/sim/DEX.md',
      package: 'pokemon-showdown', version: installed.version,
      resolved: locked.resolved, integrity: locked.integrity,
      loader: "Dex.mod('gen5')", inheritance, loader_files_sha256: loaderHashes,
    },
    types: TYPES,
    axes: {rows: '공격 타입 (attack_type)', columns: '방어 측 단일 타입', cells: '피해 배율'},
    type_count: TYPES.length, cell_count: singleChecks,
    allowed_single_type_multipliers: [0, 0.5, 1, 2],
    formula: 'getImmunity(attack, defense) ? 2 ** getEffectiveness(attack, defense) : 0',
    dual_type_rule: '두 단일 타입의 배율을 곱한다. 0배가 하나라도 있으면 결과는 0배다.',
    excludes: ['특성', '아이템', '기술 고유 효과', '날씨 등 경기 상태'],
    csv_sha256: sha256(csv),
    checks: {
      pinned_official_loader: 'passed', gen5_and_17_standard_types: 'passed',
      all_289_resolved_codes_match: 'passed', all_2601_single_dual_combinations_match: 'passed',
      known_examples: 'passed', gen5_steel_differs_from_gen6: 'passed',
    },
    single_type_checks: singleChecks, single_dual_combination_checks: combinationChecks,
    examples, generation_checks: generationChecks,
  };
  fs.mkdirSync(outputDir, {recursive: true});
  fs.writeFileSync(csvPath, csv, {flag: 'wx'});
  assert.equal(sha256(fs.readFileSync(csvPath)), info.csv_sha256);
  const saved = fs.readFileSync(csvPath, 'utf8').trimEnd().split('\n').map(line => line.split(','));
  assert.deepEqual(saved[0], ['attack_type', ...TYPES]);
  assert.equal(saved.length, 18);
  for (let i = 0; i < TYPES.length; i++) {
    assert.equal(saved[i + 1][0], TYPES[i]);
    assert.equal(saved[i + 1].length, 18);
    assert.deepEqual(saved[i + 1].slice(1).map(Number), TYPES.map(t => matrix[TYPES[i]][t]));
  }
  info.checks.saved_csv_roundtrip = 'passed';
  fs.writeFileSync(infoPath, JSON.stringify(info, null, 2) + '\n', {flag: 'wx'});
  console.log(`완료: 5세대 ${TYPES.length} × ${TYPES.length} 상성표, ${combinationChecks}개 조합 검증`);
  console.log(`상성표: ${csvPath}\n출처·검증: ${infoPath}`);
}

main();
