import 'dotenv/config';
import pg from 'pg';

const client = new pg.Client(process.env.DATABASE_URL);
await client.connect();

const s = await client.query('SELECT * FROM subjects');
console.log('Subjects:', JSON.stringify(s.rows, null, 2));

const sc = await client.query('SELECT * FROM schedules');
console.log('Schedules:', JSON.stringify(sc.rows, null, 2));

await client.end();
