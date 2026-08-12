"""
文档领域自动识别器
通过关键词频率分析判断文档所属专业领域
"""

import re
from collections import Counter


DOMAIN_KEYWORDS = {
    "AI/计算机科学": [
        "neural network", "deep learning", "machine learning", "transformer",
        "attention mechanism", "language model", "tokenization", "embedding",
        "backpropagation", "gradient descent", "convolutional", "recurrent",
        "encoder", "decoder", "fine-tuning", "inference", "pretraining",
        "loss function", "optimizer", "activation function", "batch normalization",
        "reinforcement learning", "supervised learning", "unsupervised",
        "classification", "regression", "clustering", "overfitting",
        "cross-validation", "dimensionality reduction", "feature engineering",
        "computer vision", "object detection", "semantic segmentation",
        "natural language", "speech recognition", "generative model",
        "diffusion model", "variational autoencoder", "GAN",
        "CUDA", "NVIDIA", "tensor", "pipeline", "checkpoint",
        "CPU", "memory", "thread", "process", "algorithm", "data structure",
        "database", "query", "index", "cache", "API", "REST", "graphql",
        "container", "docker", "kubernetes", "microservice", "serverless",
        "python", "javascript", "typescript", "java", "golang", "rust",
        "git", "github", "commit", "merge", "pull request", "CI/CD",
        "frontend", "backend", "full-stack", "framework", "library",
        "open source", "software", "hardware", "chip", "processor",
        "bandwidth", "latency", "throughput", "protocol", "packet",
        "programming", "compiler", "interpreter", "virtual",
        "neural", "dataset", "benchmark", "accuracy", "precision", "recall",
        "robot", "autonomous", "reinforcement", "reward", "policy gradient",
    ],
    "医学/药学": [
        "diagnosis", "treatment", "patient", "clinical", "surgery",
        "therapy", "disease", "symptom", "syndrome", "infection",
        "inflammation", "malignant", "benign", "tumor", "cancer",
        "carcinoma", "metastasis", "biopsy", "chemotherapy", "radiotherapy",
        "immunotherapy", "prognosis", "remission", "relapse", "mortality",
        "cardiovascular", "pulmonary", "hepatic", "renal", "neurological",
        "gastrointestinal", "endocrine", "metabolic", "autoimmune",
        "hypertension", "diabetes", "obesity", "asthma", "arthritis",
        "antibiotic", "antiviral", "vaccine", "immunization",
        "pharmacokinetics", "pharmacodynamics", "bioavailability",
        "half-life", "metabolism", "elimination", "excretion",
        "receptor", "agonist", "antagonist", "inhibitor", "blocker",
        "dose", "dosage", "placebo", "randomized", "double-blind",
        "trial", "cohort", "cross-sectional", "longitudinal",
        "incidence", "prevalence", "epidemiology", "etiology",
        "pathology", "pathophysiology", "histology", "cytology",
        "anesthesia", "intensive care", "emergency", "trauma",
        "transplant", "graft", "donor", "recipient",
        "gene therapy", "stem cell", "regenerative", "biomarker",
        "diagnosis imaging", "MRI", "CT scan", "ultrasound", "PET scan",
        "endoscopy", "laparoscopy", "catheter", "stent",
        "cardiac", "coronary", "ventricular", "atrial", "aortic",
        "antigen", "antibody", "lymphocyte", "macrophage", "cytokine",
        "PCR", "ELISA", "western blot", "immunohistochemistry",
        "nucleus", "mitochondria", "chromosome", "gene", "mutation",
        "oncogene", "suppressor gene", "apoptosis", "necrosis",
    ],
    "金融/经济学": [
        "asset", "liability", "equity", "revenue", "expense",
        "profit", "loss", "margin", "dividend", "yield",
        "investment", "portfolio", "diversification", "hedge",
        "stocks", "bonds", "securities", "derivatives", "options",
        "futures", "forex", "commodity", "cryptocurrency", "bitcoin",
        "interest rate", "inflation", "deflation", "recession",
        "GDP", "fiscal policy", "monetary policy", "central bank",
        "quantitative easing", "exchange rate", "balance of trade",
        "current account", "capital account", "foreign exchange",
        "treasury", "sovereign debt", "credit rating", "default",
        "bankruptcy", "restructuring", "merger", "acquisition",
        "IPO", "private equity", "venture capital", "due diligence",
        "underwriting", "prospectus", "SEC", "compliance", "audit",
        "accounting", "GAAP", "IFRS", "financial statement",
        "balance sheet", "income statement", "cash flow", "amortization",
        "depreciation", "goodwill", "impairment", "write-off",
        "tax", "tariff", "subsidy", "grant", "loan", "mortgage",
        "collateral", "leverage", "liquidity", "solvency",
        "risk management", "systemic risk", "moral hazard",
        "bull market", "bear market", "volatility", "arbitrage",
        "benchmark", "index fund", "ETF", "mutual fund",
        "shareholder", "stakeholder", "corporate governance",
        "ESG", "sustainability", "green bond", "carbon credit",
        "blockchain", "smart contract", "DeFi", "stablecoin",
        "actuarial", "annuity", "insurance", "premium", "underwriter",
        "capital market", "money market", "secondary market",
        "behavioral economics", "game theory", "utility",
        "supply", "demand", "elasticity", "oligopoly", "monopoly",
        "macroeconomics", "microeconomics", "econometrics",
    ],
    "法律/法规": [
        "statute", "regulation", "legislation", "jurisdiction",
        "plaintiff", "defendant", "litigation", "arbitration",
        "contract", "agreement", "breach", "damages", "indemnity",
        "liability", "negligence", "fraud", "tort", "remedy",
        "patent", "copyright", "trademark", "intellectual property",
        "antitrust", "merger", "acquisition", "confidentiality",
        "prosecution", "defense", "appeal", "verdict", "judgment",
        "testimony", "deposition", "subpoena", "discovery",
        "settlement", "arbitration", "mediation", "conciliation",
        "constitution", "amendment", "precedent", "common law",
        "civil law", "criminal law", "jurisprudence", "doctrine",
        "compliance", "governance", "fiduciary", "procurement",
        "sanction", "embargo", "extradition", "asylum",
        "human rights", "discrimination", "harassment", "privacy",
        "data protection", "GDPR", "CCPA", "cybersecurity",
        "compliance program", "whistleblower", "internal control",
        "due process", "rule of law", "judicial review",
        "licensing", "franchise", "partnership", "LLC", "incorporation",
    ],
    "工程/制造业": [
        "mechanism", "component", "assembly", "fabrication",
        "tolerance", "specification", "prototype", "simulation",
        "CAD", "CAM", "CNC", "machining", "welding", "casting",
        "forging", "injection molding", "additive manufacturing",
        "thermodynamics", "fluid dynamics", "stress analysis",
        "fatigue", "corrosion", "fracture", "vibration",
        "actuator", "sensor", "controller", "PLC", "SCADA",
        "circuit", "voltage", "current", "resistance", "capacitance",
        "inductance", "impedance", "semiconductor", "transistor",
        "integrated circuit", "PCB", "microcontroller", "embedded",
        "automation", "robotics", "conveyor", "process control",
        "quality control", "Six Sigma", "Lean manufacturing",
        "supply chain", "logistics", "inventory", "procurement",
        "reliability", "maintenance", "downtime", "uptime",
        "construction", "structural", "civil engineering",
        "load bearing", "seismic", "geotechnical", "hydraulic",
        "HVAC", "piping", "instrumentation", "hazardous",
    ],
}


def detect_domain(text: str) -> list:
    """自动识别文档领域
    
    Args:
        text: 文档文本内容
        
    Returns:
        [{"domain": "领域名", "score": 0.85, "matched_keywords": ["word1", ...]}, ...]
        按置信度降序排列
    """
    if not text or not text.strip():
        return []
    
    text_lower = text.lower()
    words = set(re.findall(r'[a-zA-Z]+(?:-[a-zA-Z]+)*', text_lower))
    results = []

    for domain, keywords in DOMAIN_KEYWORDS.items():
        matched = set()
        for kw in keywords:
            if kw in text_lower or kw.replace(" ", "-") in text_lower:
                matched.add(kw)
        if matched:
            score = len(matched) / len(keywords)
            unique_hits = sum(1 for m in matched if m in words)
            score = score * 0.7 + (unique_hits / max(len(keywords), 1)) * 0.3
            results.append({
                "domain": domain,
                "score": round(score, 4),
                "matched_keywords": sorted(matched),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def get_best_domain(text: str, threshold: float = 0.02) -> str:
    """获取最佳匹配领域
    
    Args:
        text: 文档文本内容
        threshold: 最低置信度阈值
        
    Returns:
        领域名，或空字符串表示未识别
    """
    results = detect_domain(text)
    if not results:
        return ""
    if results[0]["score"] >= threshold:
        return results[0]["domain"]
    return ""


def get_all_domains() -> list:
    """获取所有支持的领域列表"""
    return list(DOMAIN_KEYWORDS.keys())