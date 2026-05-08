"""
Agents module for TAO/Bittensor Multi-Agent System.

Exports all 15 specialized agents of the swarm:
1. System Check Agent
2. Protocol Research Agent
3. Subnet Discovery Agent
4. Subnet Scoring Agent
5. Wallet Watch Agent
6. Market & Trade Agent
7. Risk & Security Agent
8. Miner Engineering Agent
9. Validator Engineering Agent
10. Training & Experiment Agent
11. Infrastructure & DevOps Agent
12. Dashboard Design Agent
13. Full-Stack Development Agent
14. QA & Test Agent
15. Documentation Agent
"""

from src.agents.system_check_agent import SystemCheckAgent, AGENT_NAME as SYSTEM_CHECK_NAME
from src.agents.protocol_research_agent import ProtocolResearchAgent, AGENT_NAME as PROTOCOL_RESEARCH_NAME
from src.agents.subnet_discovery_agent import SubnetDiscoveryAgent, AGENT_NAME as SUBNET_DISCOVERY_NAME
from src.agents.subnet_scoring_agent import SubnetScoringAgent, AGENT_NAME as SUBNET_SCORING_NAME
from src.agents.wallet_watch_agent import WalletWatchAgent, AGENT_NAME as WALLET_WATCH_NAME
from src.agents.market_trade_agent import MarketTradeAgent, AGENT_NAME as MARKET_TRADE_NAME
from src.agents.risk_security_agent import RiskSecurityAgent, AGENT_NAME as RISK_SECURITY_NAME
from src.agents.miner_engineering_agent import MinerEngineeringAgent, AGENT_NAME as MINER_ENGINEERING_NAME
from src.agents.validator_engineering_agent import ValidatorEngineeringAgent, AGENT_NAME as VALIDATOR_ENGINEERING_NAME
from src.agents.training_experiment_agent import TrainingExperimentAgent, AGENT_NAME as TRAINING_EXPERIMENT_NAME
from src.agents.infra_devops_agent import InfraDevopsAgent, AGENT_NAME as INFRA_DEVOPS_NAME
from src.agents.dashboard_design_agent import DashboardDesignAgent, AGENT_NAME as DASHBOARD_DESIGN_NAME
from src.agents.fullstack_dev_agent import FullstackDevAgent, AGENT_NAME as FULLSTACK_DEV_NAME
from src.agents.qa_test_agent import QATestAgent, AGENT_NAME as QA_TEST_NAME
from src.agents.documentation_agent import DocumentationAgent, AGENT_NAME as DOCUMENTATION_NAME

__all__ = [
    "SystemCheckAgent",
    "ProtocolResearchAgent",
    "SubnetDiscoveryAgent",
    "SubnetScoringAgent",
    "WalletWatchAgent",
    "MarketTradeAgent",
    "RiskSecurityAgent",
    "MinerEngineeringAgent",
    "ValidatorEngineeringAgent",
    "TrainingExperimentAgent",
    "InfraDevopsAgent",
    "DashboardDesignAgent",
    "FullstackDevAgent",
    "QATestAgent",
    "DocumentationAgent",
]

# AGENT_NAME constants for easy reference
AGENT_NAMES: list[str] = [
    SYSTEM_CHECK_NAME,
    PROTOCOL_RESEARCH_NAME,
    SUBNET_DISCOVERY_NAME,
    SUBNET_SCORING_NAME,
    WALLET_WATCH_NAME,
    MARKET_TRADE_NAME,
    RISK_SECURITY_NAME,
    MINER_ENGINEERING_NAME,
    VALIDATOR_ENGINEERING_NAME,
    TRAINING_EXPERIMENT_NAME,
    INFRA_DEVOPS_NAME,
    DASHBOARD_DESIGN_NAME,
    FULLSTACK_DEV_NAME,
    QA_TEST_NAME,
    DOCUMENTATION_NAME,
]
