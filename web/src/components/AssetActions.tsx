import { useAuth } from "../auth/AuthContext";

export function AssetActions({onEdit, onDelete}: {onEdit: () => void; onDelete: () => void}) {
  const {canEdit, canAdmin} = useAuth();
  if (!canEdit && !canAdmin) return null;
  return <div className="asset-actions">
    {canEdit && <button className="btn btn-sm btn-secondary" onClick={onEdit}>Изменить</button>}
    {canAdmin && <button className="btn btn-sm btn-danger" onClick={onDelete}>Удалить</button>}
  </div>;
}
