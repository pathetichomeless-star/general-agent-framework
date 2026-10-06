# Governed actions

An agent that can *decide* is not automatically an agent that should be allowed to *act*. A
governed action is the middle ground: a proposed change to an external system that is expressed as
something that can be examined, authorized and recorded, rather than as a bare function call.

## Approval is structural, not a setting

The most important property is that approval is not a policy flag that can be switched off. An
external write intent that carries no approval binding **cannot be constructed at all**. The unsafe
case is not forbidden by a check that could be bypassed or misconfigured — it is not expressible in
the first place.

That distinction matters. "We check that approval happened" and "a write without approval cannot
exist" are different guarantees, and only the second one survives a careless refactor.

## Segregation of duties

The requester and the approver must be different actors. An agent — or a person — cannot approve
its own action. This is enforced where the approval decision is made, not merely encouraged by
convention.

## What the demonstration shows

In the public demo, the agent proposes a refund and the framework refuses to dispatch it before
approval. Nothing reaches the external system: no request is sent, and the authoritative record of
what was refunded stays empty until an approval exists.

Once approval is given, exactly one attempt is made. The attempt is recorded **before** the
external call, so a crash mid-flight leaves evidence of an intent that may or may not have
succeeded — which is precisely the situation the next page is about.

## What this page is not

This page describes behaviour illustrated by the public demonstration. It is not a description of
the commercial framework's internal design, and it is not a security, legal or compliance
certification.
