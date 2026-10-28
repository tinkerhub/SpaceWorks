import { useState, type FormEvent } from "react";

import { Button, ErrorText, Modal, SegmentedControl, useToast } from "../../components/ui";
import { EventFields, emptyEventForm, payloadFor, type EventFormValues } from "./EventFormFields";
import { EventSeriesFields, emptySeriesForm, seriesPayload } from "./EventSeriesForm";
import { useCreateEvent } from "./eventsApi";
import { useCreateEventSeries } from "./eventSeriesApi";
import { eventErrorText } from "./eventUi";
import { useMakerspaceCurrency } from "./paymentsApi";

type Mode = "single" | "series";

/** "New event" dialog: a one-time draft event or a draft series. */
export function EventCreateDialog({ makerspaceId, open, onClose, onCreatedEvent, onCreatedSeries }: {
  makerspaceId: number;
  open: boolean;
  onClose: () => void;
  onCreatedEvent: (eventId: number) => void;
  onCreatedSeries: (seriesId: number) => void;
}) {
  const { showToast } = useToast();
  const create = useCreateEvent(makerspaceId);
  const createSeries = useCreateEventSeries(makerspaceId);
  const currency = useMakerspaceCurrency(makerspaceId);
  const [mode, setMode] = useState<Mode>("single");
  const [values, setValues] = useState<EventFormValues>(emptyEventForm);
  const [seriesValues, setSeriesValues] = useState(emptySeriesForm);
  const pending = create.isPending || createSeries.isPending;
  const error = mode === "single" ? create.error : createSeries.error;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (mode === "single") {
      create.mutate(payloadFor(values), {
        onSuccess: (created) => {
          setValues(emptyEventForm);
          showToast("Draft event created", { tone: "success" });
          onCreatedEvent(created.id);
        },
        onError: (failure) => showToast(eventErrorText(failure), { tone: "error" }),
      });
      return;
    }
    createSeries.mutate(seriesPayload(seriesValues), {
      onSuccess: (created) => {
        setSeriesValues(emptySeriesForm);
        showToast("Draft series created", { tone: "success" });
        onCreatedSeries(created.series.id);
      },
      onError: (failure) => showToast(eventErrorText(failure), { tone: "error" }),
    });
  }

  const close = () => {
    if (!pending) onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="New event"
      description="Events start as drafts. Publish one when it is ready for sign-ups."
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={pending} onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" form="event-create-form" loading={pending} loadingLabel="Creating…">
            {mode === "single" ? "Create event" : "Create series"}
          </Button>
        </div>
      )}
    >
      <form id="event-create-form" className="grid gap-5" onSubmit={submit}>
        <SegmentedControl<Mode>
          ariaLabel="Event type"
          value={mode}
          onValueChange={setMode}
          options={[{ value: "single", label: "One-time event" }, { value: "series", label: "Series" }]}
        />
        {mode === "single"
          ? <EventFields values={values} setValues={setValues} currency={currency} />
          : <EventSeriesFields values={seriesValues} setValues={setSeriesValues} />}
        <ErrorText message={error ? eventErrorText(error) : null} />
      </form>
    </Modal>
  );
}
