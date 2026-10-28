import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { Button, Card, ConfirmDialog, DataTable, EmptyState, ErrorText, Field, Input, useToast } from "../../../components/ui";
import type { DataTableColumn } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { categoryResults, errorText, Panel, type Category, type CategoryListResponse, type Makerspace, useStaffGet } from "./shared";
import { invalidatePublicInventory } from "../queryInvalidation";
import { CategoryGuide, CodeChip } from "./CategoryGuide";

type CategoryForm = {
  name: string;
  slug: string;
  code: string;
  display_order: string;
  icon: string;
};

const emptyCategoryForm: CategoryForm = {
  name: "",
  slug: "",
  code: "",
  display_order: "",
  icon: "",
};

function categoryPayload(form: CategoryForm, includeSlug: boolean) {
  return {
    name: form.name.trim(),
    ...(includeSlug && form.slug.trim() ? { slug: form.slug.trim() } : {}),
    code: form.code.trim().toUpperCase(),
    ...(form.display_order ? { display_order: Number(form.display_order) } : {}),
    icon: form.icon.trim(),
  };
}

export function Categories({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [form, setForm] = useState<CategoryForm>(emptyCategoryForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<CategoryForm>(emptyCategoryForm);
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null);
  const categories = useStaffGet<CategoryListResponse>(
    ["categories", makerspace.id],
    `/admin/makerspace/${makerspace.id}/categories`,
  );
  const invalidateCategories = () => {
    queryClient.invalidateQueries({ queryKey: ["categories", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["inventory", makerspace.id] });
    invalidatePublicInventory(queryClient, makerspace.slug);
  };
  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${makerspace.id}/categories`, {
        method: "POST",
        body: JSON.stringify(categoryPayload(form, true)),
      }),
    onSuccess: () => {
      showToast(`${form.name.trim()} added`, { tone: "success" });
      setForm(emptyCategoryForm);
      invalidateCategories();
    },
    onError: (error) => showToast(errorText(error, "Could not add the category."), { tone: "error" }),
  });
  const update = useMutation({
    mutationFn: (category: Category) =>
      staffRequest(`/admin/categories/${category.id}`, {
        method: "PATCH",
        body: JSON.stringify(categoryPayload(editForm, false)),
      }),
    onSuccess: () => {
      showToast("Category saved", { tone: "success" });
      setEditingId(null);
      invalidateCategories();
    },
    onError: (error) => showToast(errorText(error, "Could not save the category."), { tone: "error" }),
  });
  const remove = useMutation({
    mutationFn: (category: Category) =>
      staffRequest(`/admin/categories/${category.id}`, {
        method: "DELETE",
      }).catch((error: unknown) => {
        if (error instanceof SyntaxError) return undefined;
        throw error;
      }),
    onSuccess: (_data, category) => {
      showToast(`${category.name} deleted`, { tone: "success" });
      setDeleteTarget(null);
      invalidateCategories();
    },
    onError: (error) => showToast(errorText(error, "Could not delete the category."), { tone: "error" }),
  });
  const rows = categoryResults(categories.data);
  const startEdit = (category: Category) => {
    update.reset();
    setEditingId(category.id);
    setEditForm({
      name: category.name,
      slug: category.slug,
      code: category.code ?? "",
      display_order: String(category.display_order),
      icon: category.icon ?? "",
    });
  };
  const setEdit = (key: keyof CategoryForm, value: string) => setEditForm((current) => ({ ...current, [key]: value }));
  const setNew = (key: keyof CategoryForm, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const columns: DataTableColumn<Category>[] = [
    {
      key: "code",
      header: "Code",
      sortable: true,
      render: (category) =>
        editingId === category.id ? (
          <Input className="w-24 font-mono uppercase" maxLength={4} aria-label={`Code for ${category.name}`} value={editForm.code} onChange={(event) => setEdit("code", event.target.value.toUpperCase())} />
        ) : category.code ? (
          <CodeChip>{category.code}</CodeChip>
        ) : (
          <span className="text-ink-muted">None</span>
        ),
    },
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (category) =>
        editingId === category.id ? (
          <Input className="min-w-40" aria-label={`Name for ${category.name}`} value={editForm.name} onChange={(event) => setEdit("name", event.target.value)} />
        ) : (
          <span className="font-semibold">{category.name}</span>
        ),
    },
    { key: "slug", header: "Slug", sortable: true, render: (category) => <span className="font-mono text-sm text-ink-secondary">{category.slug}</span> },
    {
      key: "display_order",
      header: "Order",
      sortable: true,
      render: (category) =>
        editingId === category.id ? (
          <Input className="w-24" aria-label={`Order for ${category.name}`} type="number" value={editForm.display_order} onChange={(event) => setEdit("display_order", event.target.value)} />
        ) : (
          <span className="tabular-nums">{category.display_order}</span>
        ),
    },
    {
      key: "icon",
      header: "Icon",
      render: (category) =>
        editingId === category.id ? (
          <Input className="w-28" aria-label={`Icon for ${category.name}`} value={editForm.icon} onChange={(event) => setEdit("icon", event.target.value)} />
        ) : (
          category.icon || <span className="text-ink-muted">None</span>
        ),
    },
    { key: "product_count", header: "Products", sortable: true, render: (category) => <span className="tabular-nums">{category.product_count}</span> },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      render: (category) =>
        editingId === category.id ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" variant="secondary" loading={update.isPending} disabled={!editForm.name.trim()} onClick={() => update.mutate(category)}>
              Save
            </Button>
            <Button size="sm" variant="quiet" disabled={update.isPending} onClick={() => setEditingId(null)}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" onClick={() => startEdit(category)}>
              Edit
            </Button>
            <Button size="sm" variant="danger-quiet" disabled={remove.isPending} onClick={() => setDeleteTarget(category)}>
              Delete…
            </Button>
          </div>
        ),
    },
  ];
  return (
    <Panel title="Categories" description="Group inventory on the public page. The code is the middle part of every item code. Lower order numbers show first.">
      <div className="grid gap-5">
        <CategoryGuide prefix={makerspace.item_code_prefix} />
        <Card as="section" aria-labelledby="new-category-heading">
          <h2 id="new-category-heading" className="mb-4 text-title text-ink">New category</h2>
          <form
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-[100px_1fr_1fr_100px_1fr_auto] xl:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              if (form.name.trim() && !create.isPending) create.mutate();
            }}
          >
            <Field label="Code" optional><Input className="font-mono uppercase" maxLength={4} placeholder="MCU" value={form.code} onChange={(event) => setNew("code", event.target.value.toUpperCase())} /></Field>
            <Field label="Name"><Input value={form.name} onChange={(event) => setNew("name", event.target.value)} /></Field>
            <Field label="Slug" optional><Input placeholder="From the name" value={form.slug} onChange={(event) => setNew("slug", event.target.value)} /></Field>
            <Field label="Order" optional><Input type="number" value={form.display_order} onChange={(event) => setNew("display_order", event.target.value)} /></Field>
            <Field label="Icon" optional><Input value={form.icon} onChange={(event) => setNew("icon", event.target.value)} /></Field>
            <div className="flex justify-end sm:col-span-2 lg:col-span-3 xl:col-span-1">
              <Button variant="primary" type="submit" startIcon={<Plus />} loading={create.isPending} disabled={!form.name.trim()}>
                Add category
              </Button>
            </div>
          </form>
          {create.error ? <div className="mt-3"><ErrorText message={create.error.message} /></div> : null}
        </Card>
        {update.error ? <ErrorText message={update.error.message} /> : null}
        {remove.error ? <ErrorText message={remove.error.message} /> : null}
        {categories.isError ? (
          <EmptyState tone="error" title="Could not load categories" description={errorText(categories.error, "Refresh the page to try again.")} />
        ) : (
          <DataTable<Category>
            columns={columns}
            data={rows}
            getRowId={(row) => row.id}
            loading={categories.isLoading}
            skeletonCols={columns.length}
            emptyTitle="No categories yet"
            emptyDescription="Add one above to group inventory on the public page."
          />
        )}
      </div>
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={deleteTarget ? `Delete ${deleteTarget.name}?` : "Delete category?"}
        message={
          deleteTarget
            ? `${deleteTarget.product_count} products will become uncategorized. The products themselves stay.`
            : ""
        }
        confirmLabel="Delete category"
        tone="danger"
        pending={remove.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) remove.mutate(deleteTarget);
        }}
      />
    </Panel>
  );
}
