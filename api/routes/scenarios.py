# from datetime import datetime, timezone

# from fastapi import (APIRouter,
#                      HTTPException,
#                      status)

# from sqlalchemy import func, select, delete, exists, and_
# from sqlalchemy.orm import  aliased, selectinload

# from db.queries import (execute_and_catch_db_error,
#                         get_account_by_username)

# # from db.base import (Thread,
# #                      Account,
# #                      Scenario,
# #                      ScenarioStep,
# #                      ScenarioEvaluation,
# #                      ScenarioTransition)

# from utils.schemas import (AddNewTransitionSchema, PatchAccountSchema,
#                            NewAccountSchema, PatchHiddenMarkAccountSchema,
#                            PatchInformationAccountSchema,
#                            PatchPhotoAccountSchema, PatchViewNameAccountSchema,
#                            UpdateProfileDataSchema,
#                            CreateAccountSchema,
#                            CreateScenarioSchema,
#                            CreateScenarioStepSchema,
#                            CreateScenarioEvaluationSchema)
# from utils.dependencies import (admin_dependency,
#                                 session_dependency)

# from utils.encrypt import encrypt_password
# from utils.base import (generate_valid_media_url)

# from config import ID_LIST_FOR_PERMISSION


# scenario_router = APIRouter(tags=['Scenarios'],
#                            prefix='/scenario')


# @scenario_router.post("/create")
# async def create_scenario(data: CreateScenarioSchema,
#                           admin: admin_dependency,
#                           session: session_dependency):
#     check_query = (
#         select(Scenario)
#         .where(
#             Scenario.name == data.name,
#         )
#     )

#     check_result = await execute_and_catch_db_error(session.execute(check_query),
#                                                     session)

#     if check_result.scalar_one_or_none():
#         raise HTTPException(status_code=400,
#                             detail='Такая запись уже есть в БД')

#     insert_data = {
#         'name': data.name,
#         'description': data.description,
#         'created_at': datetime.now(tz=timezone.utc),
#         'updated_at': datetime.now(tz=timezone.utc),
#     }

#     new_scenario = Scenario(**insert_data)

#     session.add(new_scenario)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return {
#         'id': str(new_scenario.id),
#         'name': new_scenario.name,
#         'description': new_scenario.description,
#         'created_at': new_scenario.created_at.strftime("%Y-%d-%m %H:%M"),
#         'updated_at': new_scenario.updated_at.strftime("%Y-%d-%m %H:%M"),
#     }


# @scenario_router.post("/step/create")
# async def create_scenario_step(data: CreateScenarioStepSchema,
#                                admin: admin_dependency,
#                                session: session_dependency):
#     scenario_query = (
#         select(Scenario)
#         .where(
#             Scenario.id == data.scenario_id,
#         )
#     )

#     scenario_result = await execute_and_catch_db_error(session.execute(scenario_query),
#                                                        session)

#     scenario = scenario_result.scalar_one_or_none()

#     if not scenario:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     check_query = (
#         select(ScenarioStep)
#         .where(
#             and_(
#                 ScenarioStep.scenario_id == data.scenario_id,
#                 ScenarioStep.order == data.order,
#             )
#         )
#     )

#     check_result = await execute_and_catch_db_error(session.execute(check_query),
#                                                     session)

#     if check_result.scalar_one_or_none():
#         raise HTTPException(status_code=400,
#                             detail='Шаг с таким order уже есть в этом сценарии')

#     insert_data = {
#         'scenario_id': data.scenario_id,
#         'order': data.order,
#         'name': data.name,
#         'instructions': data.instruction,
#     }

#     new_step = ScenarioStep(**insert_data)

#     session.add(new_step)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return {
#         'id': str(new_step.id),
#         'scenario_id': str(new_step.scenario_id),
#         'order': new_step.order,
#         'name': new_step.name,
#         'instruction': new_step.instructions,
#     }


# @scenario_router.delete("/delete")
# async def delete_scenario(scenario_id: int,
#                           admin: admin_dependency,
#                           session: session_dependency):
#     check_query = (
#         select(Scenario)
#         .where(
#             Scenario.id == scenario_id,
#         )
#     )

#     check_result = await execute_and_catch_db_error(session.execute(check_query),
#                                                     session)

#     scenario = check_result.scalar_one_or_none()

#     if not scenario:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     delete_query = (
#         delete(
#             Scenario
#         )\
#         .where(
#             Scenario.id == scenario_id
#         )
#     )

#     await execute_and_catch_db_error(session.execute(delete_query),
#                                      session)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return {
#         'status': 'success',
#     }


# @scenario_router.delete("/step/delete")
# async def delete_scenario_step(step_id: int,
#                                admin: admin_dependency,
#                                session: session_dependency):
#     check_query = (
#         select(ScenarioStep)
#         .where(
#             ScenarioStep.id == step_id,
#         )
#     )

#     check_result = await execute_and_catch_db_error(session.execute(check_query),
#                                                     session)

#     step = check_result.scalar_one_or_none()

#     if not step:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario step not found')

#     delete_query = (
#         delete(
#             ScenarioStep
#         )\
#         .where(
#             ScenarioStep.id == step_id
#         )
#     )

#     await execute_and_catch_db_error(session.execute(delete_query),
#                                      session)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return {
#         'status': 'success',
#     }


# @scenario_router.post("/evaluation/create")
# async def create_scenario_evaluation(data: CreateScenarioEvaluationSchema,
#                                      admin: admin_dependency,
#                                      session: session_dependency):
#     scenario_query = (
#         select(Scenario)
#         .where(
#             Scenario.id == data.scenario_id,
#         )
#     )

#     scenario_result = await execute_and_catch_db_error(session.execute(scenario_query),
#                                                        session)

#     scenario = scenario_result.scalar_one_or_none()

#     if not scenario:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     insert_data = {
#         'scenario_id': data.scenario_id,
#         'question': data.question,
#         'type': data.type.value,
#         'choices': data.choices,
#     }

#     new_evaluation = ScenarioEvaluation(**insert_data)

#     session.add(new_evaluation)

#     await execute_and_catch_db_error(session.commit(),
#                                      session,
#                                      with_rollback=True)

#     return {
#         'id': str(new_evaluation.id),
#         'scenario_id': str(new_evaluation.scenario_id),
#         'question': new_evaluation.question,
#         'type': new_evaluation.type,
#         'choices': new_evaluation.choices,
#     }


# @scenario_router.get("/list")
# async def get_scenarios(admin: admin_dependency,
#                         session: session_dependency):
#     query = (
#         select(Scenario)
#         .order_by(
#             Scenario.created_at.desc().nullslast(),
#             Scenario.id.desc(),
#         )
#     )

#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     scenarios = result.scalars().all()

#     scenario_list = []

#     for scenario in scenarios:
#         scenario_list.append({
#             'id': str(scenario.id),
#             'name': scenario.name,
#             'created_at': (
#                 scenario.created_at.strftime("%Y-%d-%m %H:%M")
#                 if scenario.created_at else ""
#             ),
#             'updated_at': (
#                 scenario.updated_at.strftime("%Y-%d-%m %H:%M")
#                 if scenario.updated_at else ""
#             ),
#         })

#     return scenario_list


# @scenario_router.get("/{scenario_id}")
# async def get_scenario_by_id(admin: admin_dependency,
#                              session: session_dependency,
#                              scenario_id: int):
#     query = (
#         select(Scenario)
#         .options(
#             selectinload(Scenario.steps),
#             selectinload(Scenario.evaluations),
#         )
#         .where(
#             Scenario.id == scenario_id,
#         )
#     )

#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     scenario = result.scalar_one_or_none()

#     if not scenario:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     step_list = []

#     for step in scenario.steps:
#         step_list.append({
#             'id': str(step.id),
#             'order': step.order,
#             'name': step.name,
#             'instruction': step.instructions,
#         })

#     evaluation_list = []

#     for evaluation in scenario.evaluations:
#         evaluation_list.append({
#             'id': str(evaluation.id),
#             'question': evaluation.question,
#             'type': evaluation.type,
#             'choices': evaluation.choices,
#         })

#     return {
#         'id': str(scenario.id),
#         'name': scenario.name,
#         'description': scenario.description,
#         'created_at': (
#             scenario.created_at.strftime("%Y-%d-%m %H:%M")
#             if scenario.created_at else ""
#         ),
#         'updated_at': (
#             scenario.updated_at.strftime("%Y-%d-%m %H:%M")
#             if scenario.updated_at else ""
#         ),
#         'steps': step_list,
#         'evaluations': evaluation_list,
#     }


# @scenario_router.get("/step/{step_id}")
# async def get_scenario_step_by_id(admin: admin_dependency,
#                                   session: session_dependency,
#                                   step_id: int):
#     query = (
#         select(ScenarioStep)
#         .options(
#             selectinload(ScenarioStep.incoming_transitions)
#             .selectinload(ScenarioTransition.conditions),
#         )
#         .where(
#             ScenarioStep.id == step_id,
#         )
#     )

#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     step = result.scalar_one_or_none()

#     if not step:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario step not found')

#     incoming_transition_list = []

#     for transition in step.incoming_transitions:
#         condition_list = []

#         for condition in transition.conditions:
#             condition_list.append({
#                 'id': str(condition.id),
#                 'evaluation_id': str(condition.evaluation_id),
#                 'operator': condition.operator,
#                 'value': condition.value,
#                 'min_probability': condition.min_probability,
#             })

#         incoming_transition_list.append({
#             'id': str(transition.id),
#             'from_step_id': str(transition.from_step_id),
#             'to_step_id': str(transition.to_step_id) if transition.to_step_id else None,
#             'conditions': condition_list,
#         })

#     return {
#         'id': str(step.id),
#         'scenario_id': str(step.scenario_id),
#         'order': step.order,
#         'name': step.name,
#         'instruction': step.instructions,
#         'incoming_transitions': incoming_transition_list,
#     }


# @scenario_router.get("/{scenario_id}/evaluations")
# async def get_evaluations_by_scenario_id(admin: admin_dependency,
#                                          session: session_dependency,
#                                          scenario_id: int):
#     scenario_query = (
#         select(Scenario)
#         .where(
#             Scenario.id == scenario_id,
#         )
#     )

#     scenario_result = await execute_and_catch_db_error(session.execute(scenario_query),
#                                                        session)

#     if not scenario_result.scalar_one_or_none():
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     query = (
#         select(ScenarioEvaluation)
#         .where(
#             ScenarioEvaluation.scenario_id == scenario_id,
#         )
#         .order_by(
#             ScenarioEvaluation.id,
#         )
#     )

#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     evaluations = result.scalars().all()

#     evaluation_list = []

#     for evaluation in evaluations:
#         evaluation_list.append({
#             'id': str(evaluation.id),
#             'scenario_id': str(evaluation.scenario_id),
#             'question': evaluation.question,
#             'type': evaluation.type,
#             'choices': evaluation.choices,
#         })

#     return evaluation_list


# @scenario_router.get("/{scenario_id}/steps")
# async def get_steps_by_scenario_id(admin: admin_dependency,
#                                    session: session_dependency,
#                                    scenario_id: int,
#                                    step_id: int | None = None):
#     scenario_query = (
#         select(Scenario)
#         .where(
#             Scenario.id == scenario_id,
#         )
#     )

#     scenario_result = await execute_and_catch_db_error(session.execute(scenario_query),
#                                                        session)

#     if not scenario_result.scalar_one_or_none():
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                             detail='Scenario not found')

#     query = (
#         select(ScenarioStep)
#         .where(
#             ScenarioStep.scenario_id == scenario_id,
#         )
#         .order_by(
#             ScenarioStep.order.desc(),
#         )
#     )

#     if step_id is not None:
#         query = query.where(
#             ScenarioStep.id != step_id,
#         )

#     result = await execute_and_catch_db_error(session.execute(query),
#                                               session)

#     steps = result.scalars().all()

#     step_list = []

#     for step in steps:
#         step_list.append({
#             'id': str(step.id),
#             'scenario_id': str(step.scenario_id),
#             'order': step.order,
#             'name': step.name,
#             'instruction': step.instructions,
#         })

#     return step_list



# async def add_new_transition(admin: admin_dependency,
#                              session: session_dependency,
#                              data: AddNewTransitionSchema):

#     pass