"""
Generate Phase 2 IMS: AI Agent Server Rack Build
100 tasks (92 work + 8 milestones) across 9 phases.
Same 5 CAMs: Alice Nguyen (SW/AI), Bob Martinez (HW),
              Carol Smith (Net/Infra), David Lee (Docs), Eva Johnson (Test/Sec)

Usage:
    python scripts/gen_ims_v2.py
Writes: data/sample_ims.xml
"""

import xml.etree.ElementTree as ET
from pathlib import Path

NS = "http://schemas.microsoft.com/project"
ET.register_namespace("", NS)

def T(name):
    return f"{{{NS}}}{name}"

def se(parent, tag, text=None):
    el = ET.SubElement(parent, T(tag))
    if text is not None:
        el.text = str(text)
    return el

def task_el(parent, uid, id_, name, start, finish, dur_h, pct,
            milestone=False, notes="", predecessors=None, wbs=None):
    """Build a <Task> element and append to parent."""
    t = ET.SubElement(parent, T("Task"))
    se(t, "UID", uid)
    se(t, "ID", id_)
    se(t, "Name", name)
    se(t, "Active", 1)
    se(t, "Manual", 0)
    se(t, "Type", 0)
    se(t, "IsNull", 0)
    se(t, "WBS", wbs if wbs is not None else id_)
    se(t, "Priority", 500)
    se(t, "Start", f"{start}T08:00:00")
    se(t, "Finish", f"{finish}T17:00:00")
    if milestone:
        se(t, "Duration", "PT0H0M0S")
    else:
        se(t, "Duration", f"PT{dur_h}H0M0S")
    se(t, "DurationFormat", 5)
    se(t, "ResumeValid", 0)
    se(t, "EffortDriven", 0)
    se(t, "Recurring", 0)
    se(t, "OverAllocated", 0)
    se(t, "Estimated", 0)
    se(t, "Milestone", 1 if milestone else 0)
    se(t, "Summary", 0)
    se(t, "Critical", 0)
    se(t, "IsSubproject", 0)
    se(t, "IsSubprojectReadOnly", 0)
    se(t, "ExternalTask", 0)
    se(t, "FixedCostAccrual", 3)
    se(t, "PercentComplete", pct)
    se(t, "ConstraintType", 0)
    se(t, "CalendarUID", -1)
    se(t, "LevelAssignments", 0)
    se(t, "LevelingCanSplit", 0)
    se(t, "LevelingDelayFormat", 5)
    se(t, "IgnoreResourceCalendar", 0)
    if notes:
        se(t, "Notes", notes)
    se(t, "HideBar", 0)
    se(t, "Rollup", 0)
    se(t, "EarnedValueMethod", 0)
    if predecessors:
        for pred in predecessors:
            pl = ET.SubElement(t, T("PredecessorLink"))
            se(pl, "PredecessorUID", pred)
            se(pl, "Type", 1)
            se(pl, "CrossProject", 0)
            se(pl, "LinkLag", 0)
            se(pl, "LagFormat", 5)
    return t


def resource_el(parent, uid, name, start, finish):
    r = ET.SubElement(parent, T("Resource"))
    se(r, "UID", uid)
    se(r, "Name", name)
    se(r, "Type", 1)
    se(r, "IsNull", 0)
    se(r, "MaxUnits", 1)
    se(r, "PeakUnits", 1)
    se(r, "OverAllocated", 0)
    se(r, "Start", f"{start}T08:00:00")
    se(r, "Finish", f"{finish}T17:00:00")
    se(r, "CanLevel", 0)
    se(r, "StandardRateFormat", 3)
    se(r, "OvertimeRateFormat", 3)
    se(r, "IsGeneric", 0)
    se(r, "IsInactive", 0)
    se(r, "IsEnterprise", 0)
    se(r, "IsBudget", 0)
    return r


def assignment_el(parent, uid, task_uid, resource_uid):
    a = ET.SubElement(parent, T("Assignment"))
    se(a, "UID", uid)
    se(a, "TaskUID", task_uid)
    se(a, "ResourceUID", resource_uid)
    se(a, "Units", 1)
    return a


def build():
    # ------------------------------------------------------------------ #
    # Root & header                                                        #
    # ------------------------------------------------------------------ #
    root = ET.Element(T("Project"))
    se(root, "SaveVersion", 14)
    se(root, "Name", "AI Agent Server Rack Build")
    se(root, "Title", "AI Agent Server Rack Build")
    se(root, "ScheduleFromStart", 0)
    se(root, "StartDate", "2026-01-05T08:00:00")
    se(root, "FinishDate", "2026-06-26T17:00:00")
    se(root, "CriticalSlackLimit", 0)
    se(root, "CurrencyDigits", 2)
    se(root, "CurrencySymbol", "$")
    se(root, "CurrencySymbolPosition", 0)
    se(root, "CalendarUID", 1)
    se(root, "MinutesPerDay", 480)
    se(root, "MinutesPerWeek", 2400)
    se(root, "DaysPerMonth", 20)
    se(root, "DurationFormat", 5)
    se(root, "WorkFormat", 2)
    se(root, "EditableActualCosts", 0)
    se(root, "HonorConstraints", 0)
    se(root, "EarnedValueMethod", 0)
    se(root, "InsertedProjectsLikeSummary", 0)
    se(root, "MultipleCriticalPaths", 0)
    se(root, "NewTasksEffortDriven", 0)
    se(root, "NewTasksEstimated", 0)
    se(root, "SplitsInProgressTasks", 0)
    se(root, "SpreadActualCost", 0)
    se(root, "SpreadPercentComplete", 0)
    se(root, "TaskUpdatesResource", 0)
    se(root, "FiscalYearStart", 0)
    se(root, "WeekStartDay", 0)
    se(root, "MoveCompletedEndsBack", 0)
    se(root, "MoveRemainingStartsBack", 0)
    se(root, "MoveRemainingStartsForward", 0)
    se(root, "MoveCompletedEndsForward", 0)
    se(root, "AutoAddNewResourcesAndTasks", 0)
    se(root, "MicrosoftProjectServerURL", 0)
    se(root, "Autolink", 0)
    se(root, "NewTaskStartDate", 0)
    se(root, "NewTasksAreManual", 0)
    se(root, "DefaultTaskEVMethod", 0)
    se(root, "ProjectExternallyEdited", 0)
    se(root, "ActualsInSync", 0)
    se(root, "RemoveFileProperties", 0)
    se(root, "AdminProject", 0)
    ET.SubElement(root, T("ExtendedAttributes"))

    # ------------------------------------------------------------------ #
    # Calendar                                                             #
    # ------------------------------------------------------------------ #
    cals = ET.SubElement(root, T("Calendars"))
    cal = ET.SubElement(cals, T("Calendar"))
    se(cal, "UID", 1)
    se(cal, "Name", "Standard")
    se(cal, "IsBaseCalendar", 1)
    se(cal, "IsBaselineCalendar", 0)
    se(cal, "BaseCalendarUID", -1)
    wds = ET.SubElement(cal, T("WeekDays"))
    for day_type, working in [(1,0),(2,1),(3,1),(4,1),(5,1),(6,1),(7,0)]:
        wd = ET.SubElement(wds, T("WeekDay"))
        se(wd, "DayType", day_type)
        se(wd, "DayWorking", working)
        if working:
            wts = ET.SubElement(wd, T("WorkingTimes"))
            for f,t in [("08:00:00","12:00:00"),("13:00:00","17:00:00")]:
                wt = ET.SubElement(wts, T("WorkingTime"))
                se(wt, "FromTime", f)
                se(wt, "ToTime", t)

    # ------------------------------------------------------------------ #
    # Tasks                                                                #
    # ------------------------------------------------------------------ #
    tasks = ET.SubElement(root, T("Tasks"))

    # Project summary (UID 0, skipped by parser)
    task_el(tasks, 0, 0, "AI Agent Server Rack Build",
            "2026-01-05", "2026-06-26", 0, 38, wbs=0)

    # ================================================================== #
    # PHASE 1 — Planning & Requirements  (Tasks 1-7, Milestone 8)        #
    # ================================================================== #
    task_el(tasks, 1, 1, "PLAN-01 Define project scope and AI workload requirements",
            "2026-01-05", "2026-01-07", 24, 100,
            notes="Scope doc approved. AI workload defined as: multi-agent orchestration (LangGraph), local LLM inference (Ollama/vLLM), vector search (Qdrant), and Claude API gateway. Peak concurrent load estimated at 50 agents.")

    task_el(tasks, 2, 2, "PLAN-02 Identify server hardware requirements and specs",
            "2026-01-05", "2026-01-07", 24, 100,
            notes="Spec sheet finalized: 4x nodes, dual Xeon Scalable, 512GB DDR5 per node, 8x NVMe SSD per node, 2x NVIDIA A100 80GB per node. Rack: 42U APC NetShelter. UPS: APC Smart-UPS 10kVA.",
            predecessors=[])

    task_el(tasks, 3, 3, "PLAN-03 Define networking and connectivity requirements",
            "2026-01-05", "2026-01-07", 24, 100,
            notes="Network design: 3 VLANs (MGMT/10.0.0.0/24, DATA/10.1.0.0/24, AI/10.2.0.0/24). 25GbE intra-rack, 10GbE uplink. Cisco Catalyst 9300 top-of-rack switch selected.")

    task_el(tasks, 4, 4, "PLAN-04 Document security and compliance requirements",
            "2026-01-05", "2026-01-07", 24, 100,
            notes="Security baseline: CIS Level 2 Ubuntu, k8s Pod Security Admission, Vault for secrets, TLS everywhere, SIEM via Wazuh. No PII data on this rack — AI workloads only.")

    task_el(tasks, 5, 5, "PLAN-05 Create initial project schedule and WBS",
            "2026-01-08", "2026-01-12", 24, 100,
            predecessors=[1,2,3,4])

    task_el(tasks, 6, 6, "PLAN-06 Identify vendors and solicit competitive quotes",
            "2026-01-08", "2026-01-12", 24, 100,
            notes="Shortlisted: Dell Technologies (servers), CDW (networking), Eaton/APC (power). GPU sourced directly from NVIDIA partner channel. Lead times: servers 3-4 weeks, GPUs 6-8 weeks.",
            predecessors=[2])

    task_el(tasks, 7, 7, "PLAN-07 Finalize hardware and software bill of materials",
            "2026-01-13", "2026-01-15", 24, 100,
            predecessors=[5,6])

    task_el(tasks, 8, 8, "MILESTONE: Project Kickoff",
            "2026-01-16", "2026-01-16", 0, 100,
            milestone=True, predecessors=[7])

    # ================================================================== #
    # PHASE 2 — Procurement  (Tasks 9-20, Milestone 21)                  #
    # ================================================================== #
    task_el(tasks, 9, 9, "PROC-01 Issue PO for server chassis and rack enclosure",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 10, 10, "PROC-02 Issue PO for CPUs, motherboards, and cooling",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 11, 11, "PROC-03 Issue PO for RAM modules and NVMe storage",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 12, 12, "PROC-04 Issue PO for GPU accelerator cards (A100)",
            "2026-01-19", "2026-01-20", 16, 100,
            notes="BLOCKER resolved: GPU allocation confirmed through NVIDIA partner — 8x A100 80GB SXM4 secured. Lead time 6 weeks.",
            predecessors=[8])

    task_el(tasks, 13, 13, "PROC-05 Issue PO for network switches and cabling",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 14, 14, "PROC-06 Issue PO for UPS and power distribution units",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 15, 15, "PROC-07 Track vendor order confirmations and hardware lead times",
            "2026-01-21", "2026-01-23", 24, 100,
            predecessors=[9,10,11,12])

    task_el(tasks, 16, 16, "PROC-08 Track networking and power gear delivery status",
            "2026-01-21", "2026-01-22", 16, 100,
            predecessors=[13,14])

    task_el(tasks, 17, 17, "PROC-09 Receive and inspect server chassis and rack",
            "2026-01-26", "2026-01-28", 24, 100,
            predecessors=[15])

    task_el(tasks, 18, 18, "PROC-10 Receive and inspect compute components (CPUs, RAM, NVMe)",
            "2026-01-26", "2026-01-28", 24, 100,
            predecessors=[15])

    task_el(tasks, 19, 19, "PROC-11 Receive and inspect GPU accelerator cards",
            "2026-01-26", "2026-01-28", 24, 100,
            predecessors=[15])

    task_el(tasks, 20, 20, "PROC-12 Receive and inspect networking gear and PDU",
            "2026-01-26", "2026-01-27", 16, 100,
            predecessors=[16])

    task_el(tasks, 21, 21, "MILESTONE: Procurement Complete",
            "2026-01-29", "2026-01-29", 0, 100,
            milestone=True, predecessors=[17,18,19,20])

    # ================================================================== #
    # PHASE 3 — Facility Preparation  (Tasks 22-27, Milestone 28)        #
    # ================================================================== #
    task_el(tasks, 22, 22, "FAC-01 Survey data center rack location and clearances",
            "2026-01-19", "2026-01-20", 16, 100,
            predecessors=[8])

    task_el(tasks, 23, 23, "FAC-02 Run and label dedicated power circuits to rack",
            "2026-01-21", "2026-01-27", 40, 100,
            predecessors=[22])

    task_el(tasks, 24, 24, "FAC-03 Run and label Ethernet and fiber cabling to rack",
            "2026-01-21", "2026-01-27", 40, 100,
            predecessors=[22])

    task_el(tasks, 25, 25, "FAC-04 Install cable management trays and patch panels",
            "2026-01-28", "2026-01-29", 16, 100,
            predecessors=[23,24])

    task_el(tasks, 26, 26, "FAC-05 Verify HVAC cooling capacity and airflow for rack",
            "2026-01-21", "2026-01-22", 16, 100,
            predecessors=[22])

    task_el(tasks, 27, 27, "FAC-06 Verify physical security, locks, and access control",
            "2026-01-21", "2026-01-22", 16, 100,
            predecessors=[22])

    task_el(tasks, 28, 28, "MILESTONE: Facility Ready",
            "2026-01-30", "2026-01-30", 0, 100,
            milestone=True, predecessors=[25,26,27])

    # ================================================================== #
    # PHASE 4 — Hardware Installation  (Tasks 29-41, Milestone 42)       #
    # ================================================================== #
    task_el(tasks, 29, 29, "HW-01 Mount server chassis and blanking panels in rack",
            "2026-02-02", "2026-02-03", 16, 100,
            predecessors=[21,28])

    task_el(tasks, 30, 30, "HW-02 Install CPUs and liquid cooling assemblies",
            "2026-02-04", "2026-02-05", 16, 100,
            predecessors=[29])

    task_el(tasks, 31, 31, "HW-03 Install DDR5 RAM in all server nodes",
            "2026-02-04", "2026-02-04", 8, 100,
            predecessors=[29])

    task_el(tasks, 32, 32, "HW-04 Install NVMe drives in all server nodes",
            "2026-02-04", "2026-02-05", 16, 100,
            predecessors=[29])

    task_el(tasks, 33, 33, "HW-05 Install NVIDIA A100 GPU accelerator cards",
            "2026-02-06", "2026-02-09", 16, 100,
            notes="GPU risers installed and torqued to spec. PCIe x16 slot verification passed on all 4 nodes. NVLink bridges installed on nodes 1 and 2.",
            predecessors=[30,31,32])

    task_el(tasks, 34, 34, "HW-06 Install 25GbE network interface cards in all nodes",
            "2026-02-10", "2026-02-10", 8, 100,
            predecessors=[33])

    task_el(tasks, 35, 35, "HW-07 Cable servers to top-of-rack Cisco 9300 switch",
            "2026-02-11", "2026-02-12", 16, 100,
            predecessors=[34])

    task_el(tasks, 36, 36, "HW-08 Mount UPS and connect to rack PDU",
            "2026-02-02", "2026-02-03", 16, 100,
            predecessors=[21,28])

    task_el(tasks, 37, 37, "HW-09 Connect rack PDU to facility power circuits",
            "2026-02-04", "2026-02-04", 8, 100,
            predecessors=[36])

    task_el(tasks, 38, 38, "HW-10 Execute power-on self-test (POST) on all nodes",
            "2026-02-12", "2026-02-13", 16, 100,
            notes="POST passed on all 4 nodes. BIOS updated to latest firmware. IPMI/iDRAC configured on management VLAN. Node 3 had a loose RAM slot — reseated and cleared.",
            predecessors=[33,37])

    task_el(tasks, 39, 39, "HW-11 Validate inter-node and switch connectivity",
            "2026-02-12", "2026-02-13", 16, 100,
            predecessors=[35,38])

    task_el(tasks, 40, 40, "HW-12 Document final hardware build of materials (BOM)",
            "2026-02-12", "2026-02-13", 16, 100,
            predecessors=[29,33])

    task_el(tasks, 41, 41, "HW-13 Photograph and label all rack installations",
            "2026-02-13", "2026-02-13", 8, 100,
            predecessors=[38,39])

    task_el(tasks, 42, 42, "MILESTONE: Hardware Installed",
            "2026-02-16", "2026-02-16", 0, 100,
            milestone=True, predecessors=[38,39,40])

    # ================================================================== #
    # PHASE 5 — OS & Base Software Stack  (Tasks 43-54, Milestone 55)    #
    # ================================================================== #
    task_el(tasks, 43, 43, "SW-01 Prepare bootable USB installers for all nodes",
            "2026-02-17", "2026-02-17", 8, 100,
            predecessors=[42])

    task_el(tasks, 44, 44, "SW-02 Install Ubuntu Server 22.04 LTS on all 4 nodes",
            "2026-02-17", "2026-02-19", 24, 100,
            predecessors=[43])

    task_el(tasks, 45, 45, "SW-03 Configure static IP addressing, hostnames, and DNS",
            "2026-02-20", "2026-02-23", 16, 100,
            predecessors=[44])

    task_el(tasks, 46, 46, "SW-04 Harden SSH config and disable root/password login",
            "2026-02-20", "2026-02-23", 16, 100,
            predecessors=[44])

    task_el(tasks, 47, 47, "SW-05 Partition and format NVMe storage volumes",
            "2026-02-20", "2026-02-23", 16, 100,
            predecessors=[44])

    task_el(tasks, 48, 48, "SW-06 Configure ZFS storage pools across all nodes",
            "2026-02-24", "2026-02-25", 16, 100,
            predecessors=[47])

    task_el(tasks, 49, 49, "SW-07 Install Docker Engine and Containerd runtime",
            "2026-02-24", "2026-02-26", 24, 100,
            predecessors=[44])

    task_el(tasks, 50, 50, "SW-08 Bootstrap Kubernetes cluster with kubeadm",
            "2026-03-02", "2026-03-04", 24, 100,
            predecessors=[49])

    task_el(tasks, 51, 51, "SW-09 Deploy Cilium CNI cluster networking plugin",
            "2026-03-05", "2026-03-09", 24, 100,
            predecessors=[50])

    task_el(tasks, 52, 52, "SW-10 Deploy Prometheus and Grafana cluster monitoring",
            "2026-03-10", "2026-03-12", 24, 100,
            notes="Prometheus stack deployed via kube-prometheus-stack helm chart. Node exporter running on all nodes, GPU metrics exporter installed. Grafana dashboards: 80% — still building out the per-GPU memory/utilization panels.",
            predecessors=[50])

    task_el(tasks, 53, 53, "SW-11 Deploy Loki log aggregation and Fluentd DaemonSet",
            "2026-03-13", "2026-03-17", 24, 100,
            notes="Fluentd DaemonSet collecting container and system logs. Loki running as StatefulSet. S3-compatible backend (MinIO) configured for long-term retention. All 4 nodes shipping logs.",
            predecessors=[52])

    task_el(tasks, 54, 54, "SW-12 Document OS configuration and base stack runbook",
            "2026-03-02", "2026-03-06", 40, 100,
            predecessors=[44])

    task_el(tasks, 55, 55, "MILESTONE: OS and Base Stack Live",
            "2026-03-18", "2026-03-18", 0, 100,
            milestone=True, predecessors=[51,52,53])

    # ================================================================== #
    # PHASE 6 — AI Stack Deployment  (Tasks 56-67, Milestone 68)         #
    # ================================================================== #
    task_el(tasks, 56, 56, "AI-01 Deploy Ollama inference engine on GPU nodes",
            "2026-03-19", "2026-03-20", 16, 100,
            notes="Ollama running on both GPU nodes. CUDA 12.2 drivers stable. Serving Llama-3 70B and Mistral 7B locally. Throughput: ~40 tokens/sec on A100 for 70B model.",
            predecessors=[55])

    task_el(tasks, 57, 57, "AI-02 Set up Harbor private container and model registry",
            "2026-03-19", "2026-03-20", 16, 100,
            notes="Harbor deployed as k8s StatefulSet with TLS. Integrated with robot accounts for CI pull. All AI service images now sourced from internal registry.",
            predecessors=[55])

    task_el(tasks, 58, 58, "AI-03 Pull, benchmark, and validate foundation LLM models",
            "2026-03-23", "2026-03-25", 24, 100,
            notes="Llama-3 70B, Mistral 7B, Phi-3-Medium, and Qwen2-72B all pulled and benchmarked. MMLU and HumanEval baselines recorded. Qwen2-72B fastest for code tasks.",
            predecessors=[56,57])

    task_el(tasks, 59, 59, "AI-04 Deploy LangGraph agent orchestration API service",
            "2026-03-26", "2026-03-30", 24, 100,
            notes="LangGraph StateGraph-based API deployed as k8s Deployment (3 replicas). Tool-calling schema finalized. Redis-backed checkpoint memory integrated. Basic multi-step agent flows working end-to-end.",
            predecessors=[58])

    task_el(tasks, 60, 60, "AI-05 Deploy Qdrant vector database (StatefulSet)",
            "2026-03-26", "2026-03-27", 16, 100,
            notes="Qdrant 1.9 deployed as k8s StatefulSet with persistent ZFS volumes. Three initial collections created: code_snippets, docs, agent_memory. gRPC API enabled.",
            predecessors=[58])

    task_el(tasks, 61, 61, "AI-06 Configure AI agent orchestration and routing layer",
            "2026-03-31", "2026-04-02", 24, 85,
            notes="BLOCKER: Agent supervisor graph 85% complete — the multi-agent handoff logic works for the two-agent case but breaks under 3+ concurrent sub-agents. Investigating LangGraph async edge routing. Expect resolution this week.",
            predecessors=[59,60])

    task_el(tasks, 62, 62, "AI-07 Deploy Claude API gateway proxy with rate limiting",
            "2026-04-06", "2026-04-07", 16, 60,
            notes="Gateway proxy deployed. Rate limiting logic in place. Still working on the response caching layer — semantic cache using Qdrant is 60% wired up.",
            predecessors=[61])

    task_el(tasks, 63, 63, "AI-08 End-to-end inference pipeline integration test",
            "2026-04-14", "2026-04-16", 24, 0,
            predecessors=[62])

    task_el(tasks, 64, 64, "AI-09 Tune GPU memory allocation and batch size parameters",
            "2026-04-20", "2026-04-21", 16, 0,
            predecessors=[63])

    task_el(tasks, 65, 65, "AI-10 Deploy model versioning and automated rollback tooling",
            "2026-04-22", "2026-04-23", 16, 0,
            predecessors=[64])

    task_el(tasks, 66, 66, "AI-11 Document AI stack architecture and API contracts",
            "2026-04-06", "2026-04-10", 40, 40,
            notes="Architecture diagram and high-level design complete. API contract (OpenAPI spec) drafted for LangGraph and Claude gateway. Model registry docs 40% done — waiting for final model list to stabilize.",
            predecessors=[61])

    task_el(tasks, 67, 67, "AI-12 Security scan all AI container images with Trivy",
            "2026-04-14", "2026-04-15", 16, 0,
            predecessors=[62])

    task_el(tasks, 68, 68, "MILESTONE: AI Stack Deployed",
            "2026-04-28", "2026-04-28", 0, 0,
            milestone=True, predecessors=[64,65,66,67])

    # ================================================================== #
    # PHASE 7 — Network & Security Hardening  (Tasks 69-83, Milestone 84)#
    # ================================================================== #
    task_el(tasks, 69, 69, "NET-01 Configure VLANs for management, data, and AI networks",
            "2026-04-29", "2026-05-01", 24, 0,
            predecessors=[68])

    task_el(tasks, 70, 70, "NET-02 Configure firewall rules and ACLs on Cisco 9300",
            "2026-05-04", "2026-05-06", 24, 0,
            predecessors=[69])

    task_el(tasks, 71, 71, "NET-03 Deploy Suricata IDS on AI and data network segments",
            "2026-05-04", "2026-05-06", 24, 0,
            predecessors=[69])

    task_el(tasks, 72, 72, "NET-04 Set up WireGuard VPN gateway for remote admin access",
            "2026-05-07", "2026-05-08", 16, 0,
            predecessors=[70])

    task_el(tasks, 73, 73, "NET-05 Harden Kubernetes RBAC and network policies",
            "2026-05-04", "2026-05-06", 24, 0,
            predecessors=[68])

    task_el(tasks, 74, 74, "NET-06 Deploy HashiCorp Vault for secrets management",
            "2026-05-07", "2026-05-08", 16, 0,
            predecessors=[73])

    task_el(tasks, 75, 75, "NET-07 Configure TLS certificates for all exposed services",
            "2026-05-11", "2026-05-13", 24, 0,
            predecessors=[72,74])

    task_el(tasks, 76, 76, "NET-08 Run full vulnerability scan (Trivy and Nessus)",
            "2026-05-14", "2026-05-15", 16, 0,
            predecessors=[75])

    task_el(tasks, 77, 77, "NET-09 Remediate all critical and high vulnerability findings",
            "2026-05-18", "2026-05-22", 40, 0,
            predecessors=[76])

    task_el(tasks, 78, 78, "NET-10 Configure centralized syslog and Wazuh SIEM",
            "2026-05-07", "2026-05-11", 24, 0,
            predecessors=[71])

    task_el(tasks, 79, 79, "NET-11 Conduct external penetration test (red team)",
            "2026-05-25", "2026-05-29", 40, 0,
            predecessors=[77,78])

    task_el(tasks, 80, 80, "NET-12 Configure network bandwidth monitoring and alerts",
            "2026-05-11", "2026-05-12", 16, 0,
            predecessors=[75])

    task_el(tasks, 81, 81, "NET-13 Configure AI inference traffic load balancing",
            "2026-05-07", "2026-05-08", 16, 0,
            predecessors=[69])

    task_el(tasks, 82, 82, "NET-14 Document network topology and security controls",
            "2026-05-18", "2026-05-22", 40, 0,
            predecessors=[75])

    task_el(tasks, 83, 83, "NET-15 Formal security review and sign-off",
            "2026-06-01", "2026-06-02", 16, 0,
            predecessors=[79,82])

    task_el(tasks, 84, 84, "MILESTONE: Network and Security Hardened",
            "2026-06-03", "2026-06-03", 0, 0,
            milestone=True, predecessors=[80,81,83])

    # ================================================================== #
    # PHASE 8 — Documentation  (Tasks 85-92)                             #
    # ================================================================== #
    task_el(tasks, 85, 85, "DOC-01 Write system administration runbook",
            "2026-06-04", "2026-06-10", 40, 0,
            predecessors=[84])

    task_el(tasks, 86, 86, "DOC-02 Write AI stack operations and troubleshooting guide",
            "2026-06-04", "2026-06-05", 16, 0,
            predecessors=[84])

    task_el(tasks, 87, 87, "DOC-03 Write hardware maintenance and parts replacement guide",
            "2026-02-17", "2026-02-19", 24, 100,
            notes="Hardware maintenance guide complete. Includes: RAM/NVMe hot-swap procedures, GPU removal/re-seat steps, UPS battery replacement schedule, and rack torque specs.",
            predecessors=[42])

    task_el(tasks, 88, 88, "DOC-04 Write disaster recovery and failback plan",
            "2026-06-04", "2026-06-10", 40, 0,
            predecessors=[84])

    task_el(tasks, 89, 89, "DOC-05 Write capacity planning and growth projection doc",
            "2026-06-11", "2026-06-15", 24, 0,
            predecessors=[84])

    task_el(tasks, 90, 90, "DOC-06 Document monitoring dashboards and alert runbooks",
            "2026-06-11", "2026-06-15", 24, 0,
            predecessors=[84])

    task_el(tasks, 91, 91, "DOC-07 Write AI services user onboarding guide",
            "2026-06-08", "2026-06-09", 16, 0,
            predecessors=[86])

    task_el(tasks, 92, 92, "DOC-08 Final documentation review and sign-off",
            "2026-06-16", "2026-06-17", 16, 0,
            predecessors=[85,87,88,89,90,91])

    # ================================================================== #
    # PHASE 9 — Testing & Acceptance  (Tasks 93-99, Milestone 100)       #
    # ================================================================== #
    task_el(tasks, 93, 93, "TEST-01 Develop system acceptance test plan",
            "2026-06-04", "2026-06-08", 24, 0,
            predecessors=[84])

    task_el(tasks, 94, 94, "TEST-02 Execute hardware burn-in and stress tests",
            "2026-06-11", "2026-06-15", 40, 0,
            predecessors=[93])

    task_el(tasks, 95, 95, "TEST-03 Execute AI inference load and performance tests",
            "2026-06-11", "2026-06-15", 40, 0,
            predecessors=[93])

    task_el(tasks, 96, 96, "TEST-04 Execute network throughput and latency tests",
            "2026-06-11", "2026-06-12", 16, 0,
            predecessors=[93])

    task_el(tasks, 97, 97, "TEST-05 Execute failover and disaster recovery tests",
            "2026-06-16", "2026-06-22", 40, 0,
            predecessors=[94,95,96])

    task_el(tasks, 98, 98, "TEST-06 Execute security acceptance tests",
            "2026-06-23", "2026-06-24", 16, 0,
            predecessors=[97])

    task_el(tasks, 99, 99, "TEST-07 Document test results and prepare acceptance report",
            "2026-06-23", "2026-06-24", 16, 0,
            predecessors=[98,92])

    task_el(tasks, 100, 100, "MILESTONE: System Accepted",
            "2026-06-25", "2026-06-25", 0, 0,
            milestone=True, predecessors=[99])

    # ================================================================== #
    # Resources                                                            #
    # ================================================================== #
    resources = ET.SubElement(root, T("Resources"))
    resource_el(resources, 1, "Alice Nguyen",  "2026-01-05", "2026-06-25")
    resource_el(resources, 2, "Bob Martinez",  "2026-01-05", "2026-06-25")
    resource_el(resources, 3, "Carol Smith",   "2026-01-05", "2026-06-25")
    resource_el(resources, 4, "David Lee",     "2026-01-05", "2026-06-25")
    resource_el(resources, 5, "Eva Johnson",   "2026-01-05", "2026-06-25")

    # ================================================================== #
    # Assignments  (task_uid -> resource_uid)                             #
    # Milestones (8,21,28,42,55,68,84,100) intentionally unassigned      #
    # ================================================================== #
    # Alice=1: PLAN-01,07 / PROC-04,11 / SW-01..12(partial) / AI-01..12(partial) / DOC-02,07
    # Bob=2:   PLAN-02,06 / PROC-01..10(partial) / HW-01..13(partial) / DOC-03 / TEST-02
    # Carol=3: PLAN-03 / PROC-05,08,12 / FAC-01..06(partial) / HW-06,07,11 / SW-03,09 / NET-01..14(partial) / TEST-04
    # David=4: PLAN-05 / HW-12,13 / SW-12 / AI-11 / NET-14 / DOC-01,04,05,06,08
    # Eva=5:   PLAN-04 / FAC-06 / SW-04 / AI-08,12 / NET-03,05,06,08,09,10,11,15 / TEST-01,03,05,06,07

    assign_map = {
        # Alice (1)
        1:1, 7:1, 12:1, 19:1,
        43:1, 44:1, 47:1, 48:1, 49:1, 50:1, 52:1, 53:1,
        56:1, 57:1, 58:1, 59:1, 60:1, 61:1, 62:1, 64:1, 65:1,
        86:1, 91:1,
        # Bob (2)
        2:2, 6:2, 9:2, 10:2, 11:2, 14:2, 15:2, 17:2, 18:2,
        29:2, 30:2, 31:2, 32:2, 33:2, 36:2, 37:2, 38:2,
        87:2, 94:2,
        # Carol (3)
        3:3, 13:3, 16:3, 20:3,
        22:3, 23:3, 24:3, 25:3, 26:3,
        34:3, 35:3, 39:3,
        45:3, 51:3,
        69:3, 70:3, 72:3, 75:3, 80:3, 81:3,
        96:3,
        # David (4)
        5:4, 40:4, 41:4, 54:4, 66:4, 82:4,
        85:4, 88:4, 89:4, 90:4, 92:4,
        # Eva (5)
        4:5, 27:5, 46:5,
        63:5, 67:5,
        71:5, 73:5, 74:5, 76:5, 77:5, 78:5, 79:5, 83:5,
        93:5, 95:5, 97:5, 98:5, 99:5,
    }

    assigns = ET.SubElement(root, T("Assignments"))
    # Summary task assignment (UID 0) — special resource -65535
    a0 = ET.SubElement(assigns, T("Assignment"))
    se(a0, "UID", 0)
    se(a0, "TaskUID", 0)
    se(a0, "ResourceUID", -65535)
    se(a0, "Units", 1)

    for assign_uid, (task_uid, res_uid) in enumerate(sorted(assign_map.items()), start=1):
        assignment_el(assigns, assign_uid, task_uid, res_uid)

    return root


def main():
    root = build()
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    out = Path("data/sample_ims.xml")
    tree.write(str(out), xml_declaration=True, encoding="utf-8")
    print(f"Written: {out}")

    # Quick validation
    import xml.etree.ElementTree as ET2
    t2 = ET2.parse(str(out))
    r2 = t2.getroot()
    ns = {"p": "http://schemas.microsoft.com/project"}
    task_els = r2.findall("p:Tasks/p:Task", ns)
    resource_els = r2.findall("p:Resources/p:Resource", ns)
    assign_els = r2.findall("p:Assignments/p:Assignment", ns)
    milestones = [t for t in task_els
                  if t.find("p:Milestone", ns) is not None
                  and t.find("p:Milestone", ns).text == "1"]
    work_tasks = [t for t in task_els
                  if t.find("p:Milestone", ns) is not None
                  and t.find("p:Milestone", ns).text == "0"
                  and t.find("p:UID", ns).text != "0"]
    print(f"Tasks total (incl summary): {len(task_els)}")
    print(f"Work tasks: {len(work_tasks)}")
    print(f"Milestones: {len(milestones)}")
    print(f"Resources: {len(resource_els)}")
    print(f"Assignments: {len(assign_els)}")

    # Per-CAM breakdown
    cam_names = {
        "1": "Alice", "2": "Bob", "3": "Carol", "4": "David", "5": "Eva"
    }
    assign_map2 = {}
    for a in assign_els:
        tuid = a.find("p:TaskUID", ns).text
        ruid = a.find("p:ResourceUID", ns).text
        assign_map2[tuid] = ruid
    cam_counts = {"1":0,"2":0,"3":0,"4":0,"5":0}
    for t in work_tasks:
        uid = t.find("p:UID", ns).text
        ruid = assign_map2.get(uid, None)
        if ruid in cam_counts:
            cam_counts[ruid] += 1
    for ruid, cnt in sorted(cam_counts.items()):
        print(f"  {cam_names[ruid]}: {cnt} work tasks")
    print(f"  Total assigned work tasks: {sum(cam_counts.values())}")


if __name__ == "__main__":
    main()
