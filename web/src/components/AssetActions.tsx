export function AssetActions({onEdit, onDelete}: {onEdit: () => void; onDelete: () => void}) {
  return <div className="asset-actions">
    <button className="btn btn-sm btn-secondary" onClick={onEdit}>Изменить</button>
    <button className="btn btn-sm btn-danger" onClick={onDelete}>Удалить</button>
  </div>;
}
