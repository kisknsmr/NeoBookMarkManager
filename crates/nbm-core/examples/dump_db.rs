use rusqlite::Connection;
use std::env;

fn main() -> anyhow::Result<()> {
    let path = env::args().nth(1).unwrap_or_else(|| "user_data.db".to_string());
    let conn = Connection::open(&path)?;

    println!("--- schema_version ---");
    let v: i64 = conn.query_row("SELECT version FROM schema_version LIMIT 1;", [], |r| r.get(0))?;
    println!("{v}");

    println!("--- open_state ---");
    let mut stmt = conn.prepare("SELECT id, file_path, content_hash, updated_at FROM open_state;")?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
        ))
    })?;
    for row in rows {
        println!("{:?}", row?);
    }

    println!("--- bookmark_meta count ---");
    let count: i64 = conn.query_row("SELECT count(*) FROM bookmark_meta;", [], |r| r.get(0))?;
    println!("{count}");

    println!("--- bookmark_meta sample ---");
    let mut stmt = conn.prepare("SELECT bookmark_id, fetched_title, fetched_at FROM bookmark_meta LIMIT 10;")?;
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, Option<String>>(1)?,
            r.get::<_, String>(2)?,
        ))
    })?;
    for row in rows {
        println!("{:?}", row?);
    }

    println!("--- url_tags count ---");
    let count: i64 = conn.query_row("SELECT count(*) FROM url_tags;", [], |r| r.get(0))?;
    println!("{count}");

    Ok(())
}
