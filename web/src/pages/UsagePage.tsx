import { useState, useEffect, useCallback } from "react"
import type { ReactNode } from "react"
import { api } from "@/lib/api-client"
import type { UsageGroupBy, UsageStats, UsageStatsItem } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  MobileListSkeleton,
  TableSkeleton,
} from "@/components/shared/PageSkeletons"
import { Skeleton } from "@/components/ui/skeleton"
import { LoadingSpinner } from "@/components/shared/LoadingSpinner"
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  BarChart3,
  CheckCircle2,
  Key,
  RotateCcwIcon,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react"

type ResetTarget =
  | { scope: "all" }
  | { scope: "group"; group_by: UsageGroupBy; group_id: string; name: string }

function formatNumber(value: number): string {
  return (value ?? 0).toLocaleString("en-US")
}

const groupByLabels: Record<UsageGroupBy, string> = {
  api_key: "按 API Key",
  kimi_account: "按 Kimi 账号",
}

function formatGroupBy(value: unknown) {
  if (value === "kimi_account") return groupByLabels.kimi_account
  return groupByLabels.api_key
}

function SummaryCard({
  icon,
  title,
  value,
  detail,
  loading,
  tone = "default",
}: {
  icon: ReactNode
  title: string
  value: ReactNode
  detail?: ReactNode
  loading: boolean
  tone?: "default" | "success" | "destructive"
}) {
  const toneClass = {
    default: "text-foreground",
    success: "text-success",
    destructive: "text-destructive",
  }[tone]

  return (
    <Card className="border-border/60 shadow-sm">
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-medium text-muted-foreground">
              {title}
            </p>
            {loading ? (
              <Skeleton className="mt-2 h-7 w-20" />
            ) : (
              <div
                className={`mt-1 truncate text-2xl font-bold tracking-tight tabular-nums ${toneClass}`}
              >
                {value}
              </div>
            )}
          </div>
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {icon}
          </div>
        </div>
        {loading ? (
          <Skeleton className="mt-3 h-4 w-28" />
        ) : detail ? (
          <div className="mt-2 text-xs text-muted-foreground">{detail}</div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function UsageMobileCard({
  item,
  groupBy,
  onReset,
}: {
  item: UsageStatsItem
  groupBy: UsageGroupBy
  onReset: (item: UsageStatsItem) => void
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {groupBy === "kimi_account" ? (
            <ShieldCheck className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <Key className="size-4 shrink-0 text-muted-foreground" />
          )}
          <p className="truncate text-sm font-medium" title={item.name}>
            {item.name}
          </p>
        </div>
        <Badge variant="secondary" className="shrink-0 text-[10px] tabular-nums">
          {item.success_rate}%
        </Badge>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">总请求</p>
          <p className="mt-1 font-semibold tabular-nums">
            {formatNumber(item.total_requests)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">成功</p>
          <p className="mt-1 font-semibold tabular-nums text-success">
            {formatNumber(item.success_requests)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">失败</p>
          <p className="mt-1 font-semibold tabular-nums text-destructive">
            {formatNumber(item.failed_requests)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">输入 tokens</p>
          <p className="mt-1 font-semibold tabular-nums">
            {formatNumber(item.input_tokens)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">输出 tokens</p>
          <p className="mt-1 font-semibold tabular-nums">
            {formatNumber(item.output_tokens)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/35 px-3 py-2">
          <p className="text-muted-foreground">合计 tokens</p>
          <p className="mt-1 font-semibold tabular-nums">
            {formatNumber(item.total_tokens)}
          </p>
        </div>
      </div>

      <div className="mt-3 flex justify-end border-t border-border/60 pt-3">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-destructive hover:text-destructive"
          onClick={() => onReset(item)}
        >
          <Trash2 className="mr-1.5 h-3.5 w-3.5" />
          重置
        </Button>
      </div>
    </div>
  )
}

export default function UsagePage() {
  const [groupBy, setGroupBy] = useState<UsageGroupBy>("api_key")
  const [data, setData] = useState<UsageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resetTarget, setResetTarget] = useState<ResetTarget | null>(null)
  const [resetting, setResetting] = useState(false)

  const fetchUsage = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await api.getUsage(groupBy)
      setData(result)
    } catch {
      setError("加载用量统计失败")
    } finally {
      setLoading(false)
    }
  }, [groupBy])

  useEffect(() => {
    fetchUsage()
  }, [fetchUsage])

  const confirmReset = async () => {
    if (!resetTarget) return
    setResetting(true)
    setError(null)
    try {
      const payload =
        resetTarget.scope === "all"
          ? { scope: "all" as const }
          : {
              scope: "group" as const,
              group_by: resetTarget.group_by,
              group_id: resetTarget.group_id,
            }
      await api.resetUsage(payload)
      setResetTarget(null)
      await fetchUsage()
    } catch {
      setError("重置失败")
    } finally {
      setResetting(false)
    }
  }

  const resetGroup = (item: UsageStatsItem) =>
    setResetTarget({
      scope: "group",
      group_by: groupBy,
      group_id: item.group_id,
      name: item.name,
    })

  const totals = data?.totals
  const items = data?.items ?? []
  const groupColumnLabel = groupBy === "kimi_account" ? "Kimi 账号" : "API Key"

  return (
    <div className="mx-auto w-full max-w-[1320px] space-y-5">
      {/* Controls */}
      <div className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <BarChart3 className="size-4 text-primary" />
          <span>统计维度</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={groupBy}
            onValueChange={(v) =>
              setGroupBy((v as UsageGroupBy) || "api_key")
            }
          >
            <SelectTrigger className="h-10 w-full min-w-0 text-xs sm:h-8 sm:w-44">
              <SelectValue>{formatGroupBy}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="api_key">按 API Key</SelectItem>
              <SelectItem value="kimi_account">按 Kimi 账号</SelectItem>
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            className="h-10 text-xs sm:h-8"
            onClick={fetchUsage}
          >
            <RotateCcwIcon className="mr-1 size-3" />
            刷新
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-10 text-xs text-destructive hover:text-destructive sm:h-8"
            onClick={() => setResetTarget({ scope: "all" })}
            disabled={loading || !data || data.items.length === 0}
          >
            <Trash2 className="mr-1 size-3" />
            全部重置
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-5">
        <SummaryCard
          icon={<Activity className="size-4" />}
          title="总请求"
          value={formatNumber(totals?.total_requests ?? 0)}
          detail={`成功率 ${totals?.success_rate ?? 0}%`}
          loading={loading}
        />
        <SummaryCard
          icon={<CheckCircle2 className="size-4" />}
          title="成功请求"
          value={formatNumber(totals?.success_requests ?? 0)}
          tone="success"
          loading={loading}
        />
        <SummaryCard
          icon={<XCircle className="size-4" />}
          title="失败请求"
          value={formatNumber(totals?.failed_requests ?? 0)}
          tone="destructive"
          loading={loading}
        />
        <SummaryCard
          icon={<ArrowDownToLine className="size-4" />}
          title="输入 tokens"
          value={formatNumber(totals?.input_tokens ?? 0)}
          loading={loading}
        />
        <SummaryCard
          icon={<ArrowUpFromLine className="size-4" />}
          title="输出 tokens"
          value={formatNumber(totals?.output_tokens ?? 0)}
          detail={`合计 ${formatNumber(totals?.total_tokens ?? 0)} tokens`}
          loading={loading}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Token 数为基于请求/响应内容的估算值，仅供参考；统计范围为最近保留的{" "}
        {data?.retention ?? "-"} 条请求日志。
      </p>

      {/* Breakdown */}
      {loading ? (
        <>
          <MobileListSkeleton items={4} className="md:hidden" />
          <TableSkeleton rows={5} columns={9} className="hidden md:block" />
        </>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-border/60 bg-card py-16 text-center shadow-sm">
          <BarChart3 className="mx-auto size-8 text-muted-foreground/30" />
          <p className="mt-3 text-sm text-muted-foreground">暂无用量数据</p>
          <p className="mt-1 text-xs text-muted-foreground/60">
            产生请求后这里会显示统计
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-3 md:hidden">
            {items.map((item) => (
              <UsageMobileCard
                key={item.group_id || item.name}
                item={item}
                groupBy={groupBy}
                onReset={resetGroup}
              />
            ))}
          </div>

          <Table
            containerClassName="hidden md:block max-h-[620px]"
            className="min-w-[920px] table-fixed"
          >
            <colgroup>
              <col className="w-[18%]" />
              <col className="w-[9%]" />
              <col className="w-[9%]" />
              <col className="w-[9%]" />
              <col className="w-[9%]" />
              <col className="w-[11%]" />
              <col className="w-[11%]" />
              <col className="w-[12%]" />
              <col className="w-[12%]" />
            </colgroup>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs">{groupColumnLabel}</TableHead>
                <TableHead className="text-right text-xs">总请求</TableHead>
                <TableHead className="text-right text-xs">成功</TableHead>
                <TableHead className="text-right text-xs">失败</TableHead>
                <TableHead className="text-right text-xs">成功率</TableHead>
                <TableHead className="text-right text-xs">输入 tokens</TableHead>
                <TableHead className="text-right text-xs">输出 tokens</TableHead>
                <TableHead className="text-right text-xs">合计 tokens</TableHead>
                <TableHead className="text-right text-xs">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.group_id || item.name}>
                  <TableCell
                    className="max-w-0 truncate text-sm font-medium text-foreground"
                    title={item.name}
                  >
                    {item.name}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {formatNumber(item.total_requests)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-success">
                    {formatNumber(item.success_requests)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-destructive">
                    {formatNumber(item.failed_requests)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                    {item.success_rate}%
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {formatNumber(item.input_tokens)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {formatNumber(item.output_tokens)}
                  </TableCell>
                  <TableCell className="text-right text-xs font-medium tabular-nums">
                    {formatNumber(item.total_tokens)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="text-destructive hover:text-destructive"
                      title="重置该项统计"
                      onClick={() => resetGroup(item)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}

      <Dialog
        open={resetTarget !== null}
        onOpenChange={(open) => {
          if (!open && !resetting) setResetTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              {resetTarget?.scope === "all" ? "重置全部用量统计" : "重置用量统计"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-2 text-sm text-muted-foreground">
            {resetTarget?.scope === "group" ? (
              <p>
                将重置{" "}
                <span className="font-medium text-foreground">
                  {resetTarget.name}
                </span>{" "}
                的用量统计。
              </p>
            ) : (
              <p>
                将重置<span className="font-medium text-foreground">全部</span>
                用量统计。
              </p>
            )}
            <p className="text-destructive">
              此操作会删除对应的请求日志记录，统计将归零且不可恢复。
            </p>
          </div>

          <DialogFooter>
            <DialogClose
              render={<Button variant="outline" disabled={resetting} />}
            >
              取消
            </DialogClose>
            <Button
              variant="destructive"
              onClick={confirmReset}
              disabled={resetting}
            >
              {resetting ? <LoadingSpinner size={16} className="mr-2" /> : null}
              确认重置
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
