# YC Application Review Context

Status: source of truth for application-answer review
Updated: 2026-07-18

This brief captures what YC reviewers will hear and see in the final founder and
product-demo videos. Use it to keep the written application consistent, clear,
and specific.

## Final Founder Video

Source: `20260716_093031_yc_clean_v1.mp4`
Duration: 59.10 seconds

### Spoken transcript

Engineers spend days tracking down product knowledge scattered between CAD
files, blueprints, and people's memory. And that poor communication costs
companies millions. I'm Shadrach, founder of InspectorPro. We anchor that
product knowledge to the CAD so engineering, manufacturing, and quality can get
the answer they need in minutes.

Take a recent example where a supplier's parts came back out of tolerance by a
few hundreds of a millimeter. Instead of taking three people spending two days
going back and forth to decide whether to accept, rework, or scrap, that
knowledge already existed. It was just scattered.

I built a working prototype that checks drawings and reasons over 3D
assemblies. Our vision is to be the product intelligence layer to accelerate
manufacturing workflows for any company building physical products from CAD.

ASR note: the transcription heard "a few hundreds of a millimeter." Engineering
context strongly suggests the spoken phrase may be "a few hundredths of a
millimeter." Confirm by listening before quoting that phrase verbatim elsewhere.

## Final Product Demo

Source: `product demo.mp4`
Duration: 2 minutes 57.80 seconds

### Spoken transcript

Manufacturers lose time and money because product knowledge is scattered across
CAD files, drawings, inspection reports, and people's heads. That is the problem
we are solving with InspectorPro. I'm Shadrach, a mechanical engineer and
founder of InspectorPro. Let me show you how it works.

I will upload this customer's piston drawing. As soon as the drawing is
uploaded, InspectorPro identifies the part and links it to its CAD model,
inspection requirements, and parent engine assembly. This is the exact model
linked to the drawing.

Now, let us move to the inspection process. The supplier has finished the part
and is now running first article inspection. Let us apply a global tolerance to
all dimensions. Assume everything passes except for the wrist pin bore.

But identifying the failure is only the first step. We also need to understand
its impact. For that, let's move to the assembly tab and ask Sage, one of our AI
agents. Sage uses first article inspection results with the piston functional
relationship in the engine to formulate the answer.

To make the impact even easier to understand, we can ask Sage to show the
affected components in motion, for example. With the impact well understood,
the last question is what to do next. This case is covered by an engineer
approved rule, so Sage gives the final disposition immediately.

And that is the value of InspectorPro. What usually takes days of emails between
supplier, quality, sourcing, and engineering now takes minutes. InspectorPro is
the product intelligence layer for manufacturers that build physical products
from CAD.

## Sage Exchanges Visible In The Demo

### Assembly impact

User: What is the impact of the failed dimension?

Sage: Wrist-pin bore diameter through the piston measured 32.00 mm, 1.95 mm
above the 30.05 mm upper limit. The oversized bore increases bearing clearance
around the piston pin, reducing radial support in the piston bosses and
introducing free play where the piston transfers load to the connecting rod
during reciprocation.

### Motion

User: Show the affected components in motion.

Sage: Showing Pin bore affected motion group at 30 RPM. Related parts are
highlighted in the assembly viewport.

### Disposition

User: What is the final disposition or step?

Sage: Disposition: Scrap and replace this piston; do not assemble it. The
wrist-pin bore measured 32.00 mm, 1.95 mm above the 30.05 mm upper limit; this
gross oversize condition is not eligible for use-as-is or rework.

## YC Review Principles

The external founder advice and review comment reduce to these rules:

1. Do not overthink the application.
2. YC is evaluating the founders and their ability to execute, not only the
   idea.
3. Explain why this founder is the right person to solve this problem.
4. Explain why now.
5. Strong answers come from a problem the founder has personally and repeatedly
   encountered, not from selecting an attractive market from a distance.
6. Write like a person, not a pitch deck.
7. Keep answers short, use real numbers, and use plain language.
8. Clarity beats complexity: clearly explain the problem, why it matters, and
   why the team is uniquely positioned to solve it.
9. Do not be excessively modest about relevant expertise and progress.
10. Execution speed matters. Keep building and report concrete progress after
    submission when useful.

## Consistency Contract For Written Answers

Application answers should reinforce, not expand beyond, the demonstrated
story:

- Problem: critical product knowledge is scattered across CAD, drawings,
  inspection records, email threads, and people's memory.
- Consequence: routine manufacturing decisions can consume several people and
  multiple days, delaying work and increasing cost.
- Product: InspectorPro connects product evidence to CAD and gives engineering,
  manufacturing, quality, and suppliers grounded answers and visual context.
- Demonstrated workflow: drawing upload -> linked model and assembly -> FAI
  failure -> assembly-impact explanation -> affected motion -> immediate
  engineer-approved disposition.
- Value: a cross-functional decision loop that normally takes days can be
  completed in minutes.
- Founder fit: Shadrach is a mechanical engineer who understands the workflow
  and built the working prototype.
- Vision: the product intelligence layer for manufacturers building physical
  products from CAD.

For each application answer, prefer one clear claim, one concrete proof point,
and only the context needed to answer the question. Do not add capabilities,
customers, savings, or technical certainty that the application cannot support.
