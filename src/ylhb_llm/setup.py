from glob import glob
from setuptools import setup

package_name = 'ylhb_llm'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='nvidia',
    maintainer_email='nvidia@todo.todo',
    description='Retail competition AI task layer.',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'retail_task_node = ylhb_llm.retail_task_node:main',
            'basic_motion_command_node = ylhb_llm.basic_motion_command_node:main',
            'voice_input_node = ylhb_llm.voice_input_node:main',
            'voice_output_node = ylhb_llm.voice_output_node:main',
            'retail_display_ui_node = ylhb_llm.retail_display_ui_node:main',
            'system_supervisor_node = ylhb_llm.system_supervisor_node:main',
        ],
    },
)
