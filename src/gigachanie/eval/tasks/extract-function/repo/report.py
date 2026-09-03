def build(rows):
    total = 0
    for r in rows:
        total += r['amount']
    avg = total / len(rows) if rows else 0
    return {'total': total, 'avg': avg}
