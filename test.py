import sqlite3,os
def search_tools(query: str) -> list:
    """Search available processing tools by name or id or short description or help containing the query string."""
    if query:
        db_path = os.path.join(os.path.dirname(__file__), 'qgis_algorithms.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name,short_description, help FROM algorithms WHERE id LIKE ? OR name LIKE ? OR short_description LIKE ? OR help LIKE ?", (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))
        results = cursor.fetchall()
        conn.close()
        #to dict

        for i in range(len(results)):
            results[i] = {
                "id": results[i][0],
                "name": results[i][1],
                "short_description": results[i][2],
                "help": results[i][3]
            }
        return results
    else:
        return []

print( search_tools("buffer"))
