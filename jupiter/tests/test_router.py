from jupiter.skills.registry import SkillRegistry, default_skills

def test_calculator_routes():
    r=SkillRegistry(default_skills())
    skill,args=r.route("calculate 2 + 3")
    assert skill.name == "calculator"
    assert args["expression"] == "2 + 3"

def test_timer_routes():
    r=SkillRegistry(default_skills())
    skill,args=r.route("set timer for 10 minutes")
    assert skill.name == "timers"
