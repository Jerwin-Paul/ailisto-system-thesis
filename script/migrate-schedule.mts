import 'dotenv/config';
import pg from 'pg';

const client = new pg.Client(process.env.DATABASE_URL);
await client.connect();

console.log('=== Schedule Migration: jsonb → separate table ===\n');

// Step 1: Create the schedules table
console.log('1. Creating schedules table...');
await client.query(`
  CREATE TABLE IF NOT EXISTS schedules (
    id SERIAL PRIMARY KEY,
    subject_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    room TEXT DEFAULT ''
  )
`);
console.log('   Done.');

// Step 2: Check if the schedule column still exists on subjects
const colCheck = await client.query(`
  SELECT column_name FROM information_schema.columns 
  WHERE table_name = 'subjects' AND column_name = 'schedule'
`);

if (colCheck.rows.length > 0) {
  // Step 3: Migrate existing jsonb data to the new table
  console.log('2. Migrating existing schedule data...');
  const subjectRows = await client.query(`SELECT id, schedule FROM subjects WHERE schedule IS NOT NULL`);

  let migrated = 0;
  for (const row of subjectRows.rows) {
    let entries: any[] = [];

    if (typeof row.schedule === 'string') {
      try { entries = JSON.parse(row.schedule); } catch { entries = []; }
    } else if (Array.isArray(row.schedule)) {
      entries = row.schedule;
    }

    for (const entry of entries) {
      if (entry && entry.day) {
        await client.query(
          `INSERT INTO schedules (subject_id, day, start_time, end_time, room) VALUES ($1, $2, $3, $4, $5)`,
          [row.id, entry.day || '', entry.startTime || '', entry.endTime || '', entry.room || '']
        );
        migrated++;
      }
    }
  }
  console.log(`   Migrated ${migrated} schedule entries from ${subjectRows.rows.length} subjects.`);

  // Step 4: Drop the schedule column
  console.log('3. Dropping schedule column from subjects...');
  await client.query(`ALTER TABLE subjects DROP COLUMN schedule`);
  console.log('   Done.');
} else {
  console.log('2. Schedule column already removed, skipping migration.');
}

// Verify
console.log('\n=== Verification ===');
const schedulesCount = await client.query(`SELECT COUNT(*) as count FROM schedules`);
console.log(`Schedules table has ${schedulesCount.rows[0].count} rows.`);

const subjectCols = await client.query(`
  SELECT column_name FROM information_schema.columns WHERE table_name = 'subjects' ORDER BY ordinal_position
`);
console.log(`Subjects columns: ${subjectCols.rows.map(r => r.column_name).join(', ')}`);

await client.end();
console.log('\nMigration complete!');
