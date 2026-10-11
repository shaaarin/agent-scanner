import { api } from "../api/client";
import type { Scan } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ScansTable } from "../components/ScansTable";

// Глобальный список сканирований. Создание сканов -- внутри актива
// (раздел «Активы» -> карточка актива -> «Новое сканирование»); настройки
// сканеров форма берёт из реестра GET /scanners.

export function Scans() {
  return (
    <div>
      <PageHeader
        title="Сканирования"
        description="Все запуски по вашим активам: агентам, MCP и skills. Создать новое можно в карточке актива."
      />
      <ScansTable
        onLoad={() => api.get<Scan[]>("/scans")}
        emptyTitle="Здесь появятся ваши сканирования"
        emptyText="Откройте раздел «Активы», выберите актив и создайте для него сканирование."
      />
    </div>
  );
}
