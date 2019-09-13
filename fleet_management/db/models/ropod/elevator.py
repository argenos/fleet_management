import logging

from pymodm import EmbeddedMongoModel, fields, MongoModel
from pymodm.context_managers import switch_collection
from pymongo.errors import ServerSelectionTimeoutError
from ropod.structs.elevator import ElevatorRequestStatus

from fleet_management.db.models.ropod.ropod import Ropod
from fleet_management.db.models.task import Task
from fleet_management.db.queries.sets.ropod.elevators import ElevatorRequestManager
from fleet_management.utils.messages import Document, Message


class ElevatorStatus(EmbeddedMongoModel):
    floor = fields.IntegerField()
    calls = fields.IntegerField()
    is_available = fields.BooleanField()
    door_open_at_goal_floor = fields.BooleanField()
    door_open_at_start_floor = fields.BooleanField()

    class Meta:
        ignore_unknown_fields = True


class Elevator(MongoModel):
    id = fields.IntegerField(primary_key=True)
    elevator_id = fields.CharField()
    status = fields.EmbeddedDocumentField(ElevatorStatus)


class ElevatorRequest(MongoModel):
    query_id = fields.UUIDField(primary_key=True)
    status = fields.IntegerField(default=ElevatorRequestStatus.PENDING)
    elevator_id = fields.ReferenceField(Elevator)
    robot_id = fields.ReferenceField(Ropod)
    command = fields.CharField()
    start_floor = fields.IntegerField()
    goal_floor = fields.IntegerField()
    task_id = fields.ReferenceField(Task, blank=True)
    load = fields.CharField()
    operational_mode = fields.CharField(default="ROBOT")

    objects = ElevatorRequestManager()

    class Meta:
        archive_collection = 'elevator_request_archive'
        ignore_unknown_fields = True

    def save(self):
        try:
            super().save(cascade=True)
        except ServerSelectionTimeoutError:
            logging.warning('Could not save models to MongoDB')

    def archive(self):
        with switch_collection(RobotRequest, RobotRequest.Meta.archive_collection):
            super().save()
        self.delete()

    def to_dict(self):
        dict_repr = self.to_son().to_dict()
        dict_repr.pop('_cls')
        dict_repr["query_id"] = str(dict_repr.pop('_id'))
        return dict_repr


class RobotRequest(ElevatorRequest):

    def assign_elevator(self, elevator_id):
        self.elevator_id = elevator_id
        self.save()

    def update_status(self, status):
        if status == ElevatorRequestStatus.COMPLETED:
            self.archive()
        else:
            self.status = status
            self.save()

    @classmethod
    def from_msg(cls, payload):
        document = Document.from_msg(payload)
        document['_id'] = document.pop('query_id')
        request = RobotRequest.from_document(document)
        request.save()
        return request

    def to_msg(self):
        return Message.from_dict(self.to_dict(), "ELEVATOR-CMD")