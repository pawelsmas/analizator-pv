"""
SQLite Database Management for PV Optimizer Projects
"""
import aiosqlite
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DATABASE_PATH = os.environ.get('DATABASE_PATH', '/app/data/projects.db')

async def init_db():
    """Initialize database with required tables"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Projects table - main project information
        await db.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                client_name TEXT NOT NULL,
                client_nip TEXT,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Project data table - stores all calculation results as JSON
        await db.execute('''
            CREATE TABLE IF NOT EXISTS project_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                data_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        ''')

        # Create indexes for better performance
        await db.execute('CREATE INDEX IF NOT EXISTS idx_projects_nip ON projects(client_nip)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_project_data_type ON project_data(project_id, data_type)')

        await db.commit()
        print(f"Database initialized at {DATABASE_PATH}")

async def create_project(
    project_name: str,
    client_name: str,
    client_nip: Optional[str] = None,
    description: Optional[str] = None
) -> int:
    """Create a new project and return its ID"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO projects (project_name, client_name, client_nip, description)
            VALUES (?, ?, ?, ?)
        ''', (project_name, client_name, client_nip, description))
        await db.commit()
        return cursor.lastrowid

async def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    """Get project by ID"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM projects WHERE id = ?
        ''', (project_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None

async def get_all_projects(
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Get all projects with optional filtering"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        query = 'SELECT * FROM projects WHERE 1=1'
        params = []

        if status:
            query += ' AND status = ?'
            params.append(status)

        if search:
            query += ' AND (project_name LIKE ? OR client_name LIKE ? OR client_nip LIKE ?)'
            search_pattern = f'%{search}%'
            params.extend([search_pattern, search_pattern, search_pattern])

        query += ' ORDER BY updated_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def update_project(
    project_id: int,
    project_name: Optional[str] = None,
    client_name: Optional[str] = None,
    client_nip: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None
) -> bool:
    """Update project information"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        updates = []
        params = []

        if project_name is not None:
            updates.append('project_name = ?')
            params.append(project_name)
        if client_name is not None:
            updates.append('client_name = ?')
            params.append(client_name)
        if client_nip is not None:
            updates.append('client_nip = ?')
            params.append(client_nip)
        if description is not None:
            updates.append('description = ?')
            params.append(description)
        if status is not None:
            updates.append('status = ?')
            params.append(status)

        if not updates:
            return False

        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(project_id)

        query = f'UPDATE projects SET {", ".join(updates)} WHERE id = ?'
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.rowcount > 0

async def delete_project(project_id: int) -> bool:
    """Delete project and all its data"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Delete project data first
        await db.execute('DELETE FROM project_data WHERE project_id = ?', (project_id,))
        # Delete project
        cursor = await db.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        await db.commit()
        return cursor.rowcount > 0

async def save_project_data(
    project_id: int,
    data_type: str,
    data: Dict[str, Any]
) -> int:
    """Save or update project data of specific type"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Delete existing data of this type for the project
        await db.execute('''
            DELETE FROM project_data WHERE project_id = ? AND data_type = ?
        ''', (project_id, data_type))

        # Insert new data
        cursor = await db.execute('''
            INSERT INTO project_data (project_id, data_type, data_json)
            VALUES (?, ?, ?)
        ''', (project_id, data_type, json.dumps(data, ensure_ascii=False)))

        # Update project timestamp
        await db.execute('''
            UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (project_id,))

        await db.commit()
        return cursor.lastrowid

async def get_project_data(
    project_id: int,
    data_type: Optional[str] = None
) -> Dict[str, Any]:
    """Get project data, optionally filtered by type"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        if data_type:
            cursor = await db.execute('''
                SELECT data_type, data_json FROM project_data
                WHERE project_id = ? AND data_type = ?
            ''', (project_id, data_type))
            row = await cursor.fetchone()
            if row:
                return {row['data_type']: json.loads(row['data_json'])}
            return {}
        else:
            cursor = await db.execute('''
                SELECT data_type, data_json FROM project_data WHERE project_id = ?
            ''', (project_id,))
            rows = await cursor.fetchall()
            return {row['data_type']: json.loads(row['data_json']) for row in rows}

async def get_full_project_export(project_id: int) -> Optional[Dict[str, Any]]:
    """Get complete project with all data for export"""
    project = await get_project(project_id)
    if not project:
        return None

    data = await get_project_data(project_id)

    return {
        'project': project,
        'data': data,
        'exported_at': datetime.now().isoformat(),
        'version': '1.8'
    }

async def get_projects_by_nip(client_nip: str) -> List[Dict[str, Any]]:
    """Get all projects for a specific client NIP"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM projects WHERE client_nip = ? ORDER BY updated_at DESC
        ''', (client_nip,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
